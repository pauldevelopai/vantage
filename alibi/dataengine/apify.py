"""
Vantage Data Engine — Apify client (§9).

Thin wrapper over the Apify REST API: run an actor and get its dataset items.
Deliberately small — the engine's value is in normalisation, the guard and the
provenance/retention store, not in this transport.

Fail-safe: no token or any error returns None (never raises, never fabricates).
Set APIFY_TOKEN to enable. Without it the engine still runs — it just has no
live source, and the store honestly reports empty.
"""

import os
from typing import Any, Dict, List, Optional

import requests

APIFY_BASE = "https://api.apify.com/v2"


class ApifyClient:
    def __init__(self, token: Optional[str] = None, timeout: int = 120):
        self.token = token or os.getenv("APIFY_TOKEN")
        self.timeout = timeout

    def available(self) -> bool:
        return bool(self.token)

    def run_actor_sync(
        self,
        actor: str,
        actor_input: Optional[Dict[str, Any]] = None,
    ) -> Optional[List[Dict[str, Any]]]:
        """Run an Apify actor and return its dataset items.

        `actor` is the actor id, e.g. "apify/website-content-crawler" — the slash
        is converted to the tilde form the API expects.

        Returns the item list, or None on any failure (no token, HTTP error,
        bad payload). Never raises.
        """
        if not self.available():
            print("[DataEngine] APIFY_TOKEN not set — no live Apify source.")
            return None

        actor_path = actor.replace("/", "~")
        url = f"{APIFY_BASE}/acts/{actor_path}/run-sync-get-dataset-items"

        try:
            resp = requests.post(
                url,
                params={"token": self.token},
                json=actor_input or {},
                timeout=self.timeout,
            )
            resp.raise_for_status()
            items = resp.json()
            if not isinstance(items, list):
                print(f"[DataEngine] Apify actor {actor} returned a non-list payload.")
                return None
            return items
        except Exception as e:
            print(f"[DataEngine] Apify actor {actor} failed: {e}")
            return None
