"""
Vantage Data Engine — Apify client (§9).

Thin wrapper over the Apify REST API: run an actor and get its dataset items.
Deliberately small — the engine's value is in normalisation, the guard and the
provenance/retention store, not in this transport.

Transport is START-AND-POLL, not run-sync: the Google Places actor routinely
takes 2-5 minutes, which blew past a single HTTP read timeout and lost results
that Apify had already billed for. Starting the run and polling its status
survives slow actors; on deadline we best-effort ABORT the run so a hung actor
cannot silently burn credit.

Fail-safe: no token or any error returns None (never raises, never fabricates).
Set APIFY_TOKEN to enable. Without it the engine still runs — it just has no
live source, and the store honestly reports empty.
"""

import os
import time
from typing import Any, Dict, List, Optional

import requests

APIFY_BASE = "https://api.apify.com/v2"

# Statuses reported by GET /actor-runs/{id} while the run is still going.
_IN_PROGRESS = ("READY", "RUNNING")


class ApifyClient:
    def __init__(
        self,
        token: Optional[str] = None,
        timeout: int = 600,
        poll_interval: int = 10,
    ):
        """`timeout` is the overall deadline for one actor run (start -> items),
        not a per-request read timeout. Individual HTTP calls are quick; the
        actor itself is what takes minutes."""
        self.token = token or os.getenv("APIFY_TOKEN")
        self.timeout = timeout
        self.poll_interval = poll_interval

    def available(self) -> bool:
        return bool(self.token)

    # --- internals ---------------------------------------------------------- #

    def _get(self, path: str, **params: Any) -> Dict[str, Any]:
        resp = requests.get(
            f"{APIFY_BASE}{path}",
            params={"token": self.token, **params},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def _abort_run(self, run_id: str) -> None:
        """Best-effort abort so a deadline-exceeded run stops spending credit."""
        try:
            requests.post(
                f"{APIFY_BASE}/actor-runs/{run_id}/abort",
                params={"token": self.token},
                timeout=30,
            )
        except Exception:
            pass  # the deadline error is already being reported; don't mask it

    # --- public ------------------------------------------------------------- #

    def run_actor_sync(
        self,
        actor: str,
        actor_input: Optional[Dict[str, Any]] = None,
    ) -> Optional[List[Dict[str, Any]]]:
        """Run an Apify actor and return its dataset items.

        `actor` is the actor id, e.g. "apify/website-content-crawler" — the slash
        is converted to the tilde form the API expects.

        Blocks until the run finishes (polling), up to `self.timeout` seconds.
        Returns the item list, or None on any failure (no token, HTTP error,
        run failed, deadline exceeded). Never raises.
        """
        if not self.available():
            print("[DataEngine] APIFY_TOKEN not set — no live Apify source.")
            return None

        actor_path = actor.replace("/", "~")

        try:
            # 1. Start the run.
            resp = requests.post(
                f"{APIFY_BASE}/acts/{actor_path}/runs",
                params={"token": self.token},
                json=actor_input or {},
                timeout=30,
            )
            resp.raise_for_status()
            run = resp.json().get("data") or {}
            run_id = run.get("id")
            dataset_id = run.get("defaultDatasetId")
            if not run_id or not dataset_id:
                print(f"[DataEngine] Apify actor {actor} start returned no run/dataset id.")
                return None

            # 2. Poll until it finishes or the deadline passes.
            deadline = time.monotonic() + self.timeout
            status = run.get("status", "READY")
            while status in _IN_PROGRESS:
                if time.monotonic() >= deadline:
                    self._abort_run(run_id)
                    print(
                        f"[DataEngine] Apify actor {actor} exceeded {self.timeout}s "
                        f"deadline — run {run_id} aborted."
                    )
                    return None
                time.sleep(self.poll_interval)
                status = (self._get(f"/actor-runs/{run_id}").get("data") or {}).get("status")

            if status != "SUCCEEDED":
                print(f"[DataEngine] Apify actor {actor} run {run_id} ended {status}.")
                return None

            # 3. Fetch the dataset items.
            items = self._get(f"/datasets/{dataset_id}/items", clean="true")
            if not isinstance(items, list):
                print(f"[DataEngine] Apify actor {actor} returned a non-list payload.")
                return None
            return items
        except Exception as e:
            print(f"[DataEngine] Apify actor {actor} failed: {e}")
            return None
