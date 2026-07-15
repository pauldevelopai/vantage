"""
Vantage Camera Bridge — cloud-side protocol.

A cloud-hosted Vantage cannot scan a user's home/office WiFi (browsers and cloud
servers can't reach a private LAN). So a small **bridge agent** runs on the
user's network, connects OUTBOUND to Vantage, and does the scanning locally.
This module is the cloud side of that protocol:

  1. Pairing    — an admin mints a short-lived, single-use pairing code; the
                  agent redeems it once to become a registered bridge with its
                  own long-lived token. (Plaintext token returned ONCE.)
  2. Scan jobs  — the console enqueues a scan for a bridge; the agent polls,
                  runs the scanner on the LAN, and posts results back.
  3. Results    — the console reads the job's results (the same DiscoveredCamera
                  dicts the local scanner produces) and shows them.

Security:
  * Only token HASHES are stored; the plaintext bridge token is shown once at
    registration and never again. Auth uses a constant-time compare.
  * Pairing codes are single-use and expire (default 15 min).
  * The agent connects outbound only — no inbound ports on the user's network.

Fail-safe + honest empty states throughout: unknown ids return None / [], never
fabricated data; nothing raises on bad input.
"""

import hashlib
import hmac
import json
import os
import secrets
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

PAIRING_TTL_MINUTES = 15
BRIDGE_ONLINE_SECONDS = 90          # heartbeat fresher than this = "online"
MAX_JOBS_RETAINED = 200             # cap stored jobs/results


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _now() -> datetime:
    return datetime.utcnow()


@dataclass
class Bridge:
    bridge_id: str
    name: str
    token_hash: str
    created_by: str
    created_at: str
    last_seen: Optional[str] = None
    site_hint: str = ""             # e.g. the LAN subnet the agent reported

    def is_online(self, now: Optional[datetime] = None) -> bool:
        if not self.last_seen:
            return False
        now = now or _now()
        try:
            return (now - datetime.fromisoformat(self.last_seen)).total_seconds() <= BRIDGE_ONLINE_SECONDS
        except Exception:
            return False

    def public_dict(self, now: Optional[datetime] = None) -> Dict[str, Any]:
        """Safe to send to the console — never includes the token hash."""
        return {
            "bridge_id": self.bridge_id,
            "name": self.name,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "last_seen": self.last_seen,
            "site_hint": self.site_hint,
            "online": self.is_online(now),
        }


@dataclass
class PairingCode:
    code: str
    created_by: str
    created_at: str
    expires_at: str
    used_by: Optional[str] = None   # bridge_id once redeemed

    def is_valid(self, now: Optional[datetime] = None) -> bool:
        if self.used_by:
            return False
        now = now or _now()
        try:
            return now < datetime.fromisoformat(self.expires_at)
        except Exception:
            return False


@dataclass
class ScanJob:
    job_id: str
    bridge_id: str
    status: str = "pending"         # pending | running | done | error
    params: Dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""
    results: List[Dict[str, Any]] = field(default_factory=list)
    error: str = ""

    def public_dict(self) -> Dict[str, Any]:
        return asdict(self)


class BridgeRegistry:
    """JSON-file-backed registry of bridges, pairing codes, and scan jobs."""

    def __init__(self, storage_path: str = "alibi/data/camera_bridges.json"):
        self.storage_path = storage_path
        os.makedirs(os.path.dirname(storage_path) or ".", exist_ok=True)
        self._bridges: Dict[str, Bridge] = {}
        self._codes: Dict[str, PairingCode] = {}
        self._jobs: Dict[str, ScanJob] = {}
        self._load()

    # --- persistence ------------------------------------------------------ #

    def _load(self):
        if not os.path.exists(self.storage_path):
            return
        try:
            with open(self.storage_path) as f:
                data = json.load(f)
            self._bridges = {k: Bridge(**v) for k, v in data.get("bridges", {}).items()}
            self._codes = {k: PairingCode(**v) for k, v in data.get("codes", {}).items()}
            self._jobs = {k: ScanJob(**v) for k, v in data.get("jobs", {}).items()}
        except Exception as e:
            print(f"[Bridge] load error: {e}")

    def _save(self):
        data = {
            "bridges": {k: asdict(v) for k, v in self._bridges.items()},
            "codes": {k: asdict(v) for k, v in self._codes.items()},
            "jobs": {k: asdict(v) for k, v in self._jobs.items()},
        }
        tmp = self.storage_path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, self.storage_path)

    # --- pairing ---------------------------------------------------------- #

    def create_pairing_code(self, created_by: str, now: Optional[datetime] = None) -> PairingCode:
        now = now or _now()
        code = secrets.token_hex(4).upper()   # 8 hex chars, easy to copy
        pc = PairingCode(
            code=code,
            created_by=created_by,
            created_at=now.isoformat(),
            expires_at=(now + timedelta(minutes=PAIRING_TTL_MINUTES)).isoformat(),
        )
        self._codes[code] = pc
        self._save()
        return pc

    def redeem_pairing_code(
        self, code: str, name: str, site_hint: str = "", now: Optional[datetime] = None
    ) -> Optional[Dict[str, str]]:
        """Redeem a pairing code -> a new bridge. Returns {bridge_id, token}
        with the plaintext token ONCE, or None if the code is invalid/expired."""
        pc = self._codes.get((code or "").strip().upper())
        if not pc or not pc.is_valid(now):
            return None

        now = now or _now()
        bridge_id = "brg_" + secrets.token_hex(8)
        token = secrets.token_urlsafe(32)
        self._bridges[bridge_id] = Bridge(
            bridge_id=bridge_id,
            name=name or "Vantage Bridge",
            token_hash=_hash_token(token),
            created_by=pc.created_by,
            created_at=now.isoformat(),
            last_seen=now.isoformat(),
            site_hint=site_hint,
        )
        pc.used_by = bridge_id
        self._save()
        return {"bridge_id": bridge_id, "token": token}

    # --- auth / heartbeat ------------------------------------------------- #

    def authenticate(self, bridge_id: str, token: str) -> bool:
        b = self._bridges.get(bridge_id)
        if not b or not token:
            return False
        return hmac.compare_digest(b.token_hash, _hash_token(token))

    def heartbeat(self, bridge_id: str, site_hint: Optional[str] = None,
                  now: Optional[datetime] = None) -> bool:
        b = self._bridges.get(bridge_id)
        if not b:
            return False
        b.last_seen = (now or _now()).isoformat()
        if site_hint:
            b.site_hint = site_hint
        self._save()
        return True

    def list_bridges(self, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
        return [b.public_dict(now) for b in
                sorted(self._bridges.values(), key=lambda x: x.created_at, reverse=True)]

    def get_bridge(self, bridge_id: str) -> Optional[Bridge]:
        return self._bridges.get(bridge_id)

    def remove_bridge(self, bridge_id: str) -> bool:
        """Unpair a PC. Its token stops working immediately; the agent on that PC
        can no longer authenticate (it must be re-paired to record again). Also
        drops any of its queued/finished scan jobs. Returns False if unknown."""
        if bridge_id not in self._bridges:
            return False
        del self._bridges[bridge_id]
        self._jobs = {jid: j for jid, j in self._jobs.items() if j.bridge_id != bridge_id}
        self._save()
        return True

    def rename_bridge(self, bridge_id: str, name: str) -> Optional[Bridge]:
        """Relabel a PC (e.g. 'Mac (temporary)' → 'Office PC'). Returns None if
        unknown."""
        b = self._bridges.get(bridge_id)
        if not b:
            return None
        name = (name or "").strip()
        if name:
            b.name = name
            self._save()
        return b

    # --- scan jobs -------------------------------------------------------- #

    def enqueue_scan(self, bridge_id: str, params: Optional[Dict[str, Any]] = None,
                     now: Optional[datetime] = None) -> Optional[ScanJob]:
        if bridge_id not in self._bridges:
            return None
        now = now or _now()
        job = ScanJob(
            job_id="job_" + secrets.token_hex(8),
            bridge_id=bridge_id,
            params=params or {},
            created_at=now.isoformat(),
            updated_at=now.isoformat(),
        )
        self._jobs[job.job_id] = job
        self._prune_jobs()
        self._save()
        return job

    def claim_next_job(self, bridge_id: str, now: Optional[datetime] = None) -> Optional[ScanJob]:
        """The agent calls this to pick up the oldest pending job for it."""
        pending = sorted(
            (j for j in self._jobs.values()
             if j.bridge_id == bridge_id and j.status == "pending"),
            key=lambda j: j.created_at,
        )
        if not pending:
            return None
        job = pending[0]
        job.status = "running"
        job.updated_at = (now or _now()).isoformat()
        self._save()
        return job

    def submit_results(self, bridge_id: str, job_id: str,
                       cameras: List[Dict[str, Any]], error: str = "",
                       now: Optional[datetime] = None) -> bool:
        job = self._jobs.get(job_id)
        if not job or job.bridge_id != bridge_id:
            return False
        job.status = "error" if error else "done"
        job.error = error or ""
        job.results = cameras or []
        job.updated_at = (now or _now()).isoformat()
        self._save()
        return True

    def get_job(self, job_id: str) -> Optional[ScanJob]:
        return self._jobs.get(job_id)

    def latest_completed_scan(self, bridge_id: str) -> Optional[ScanJob]:
        """The most recently finished scan for a bridge — so the console can show
        results on page load, independent of the live poll that ran at scan time."""
        done = [j for j in self._jobs.values()
                if j.bridge_id == bridge_id and j.status == "done"]
        if not done:
            return None
        return max(done, key=lambda j: j.updated_at)

    def _prune_jobs(self):
        if len(self._jobs) <= MAX_JOBS_RETAINED:
            return
        keep = sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)[:MAX_JOBS_RETAINED]
        self._jobs = {j.job_id: j for j in keep}


_registry: Optional[BridgeRegistry] = None


def get_bridge_registry() -> BridgeRegistry:
    global _registry
    if _registry is None:
        _registry = BridgeRegistry()
    return _registry
