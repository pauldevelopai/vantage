"""
End-to-end HTTP test of the camera-bridge endpoints.

Drives the whole "just hit scan" round-trip through the real FastAPI app:
  admin pairs -> agent registers -> admin enqueues scan -> agent polls & claims
  -> agent submits results -> admin reads them.

Admin auth is stubbed via a dependency override; the AGENT side uses the real
bridge-token header auth (not overridden), so the token/credential path is
genuinely exercised.
"""

import pytest

pytestmark = pytest.mark.filterwarnings("ignore")

from fastapi.testclient import TestClient

import alibi.cameras.bridge as bridge_mod
from alibi.cameras.bridge import BridgeRegistry
from alibi.alibi_api import app
from alibi.auth import get_current_user, User, Role


@pytest.fixture
def client(tmp_path):
    # Point the global registry at a temp file.
    bridge_mod._registry = BridgeRegistry(storage_path=str(tmp_path / "bridges.json"))

    admin = User(username="admin", password_hash="x", role=Role.ADMIN, full_name="Admin")
    app.dependency_overrides[get_current_user] = lambda: admin
    yield TestClient(app)
    app.dependency_overrides.clear()
    bridge_mod._registry = None


def test_full_bridge_flow(client):
    # 1. Admin mints a pairing code.
    r = client.post("/cameras/bridge/pair")
    assert r.status_code == 200
    code = r.json()["code"]
    assert code

    # 2. Agent registers with the code (no admin auth — public register).
    r = client.post("/cameras/bridge/register",
                    json={"code": code, "name": "Home WiFi", "site_hint": "192.168.1.0/24"})
    assert r.status_code == 200
    creds = r.json()
    bridge_id, token = creds["bridge_id"], creds["token"]
    agent_headers = {"X-Bridge-Id": bridge_id, "X-Bridge-Token": token}

    # 3. Admin sees it online (heartbeat was set at registration).
    r = client.get("/cameras/bridge")
    bridges = r.json()["bridges"]
    assert bridges and bridges[0]["bridge_id"] == bridge_id
    assert bridges[0]["online"] is True
    assert "token_hash" not in bridges[0]

    # 4. Admin enqueues a scan.
    r = client.post(f"/cameras/bridge/{bridge_id}/scan", json={"cidr": "192.168.1.0/24"})
    assert r.status_code == 200
    job_id = r.json()["job_id"]

    # 5. Agent polls for the job (with its token) and claims it.
    r = client.get("/cameras/bridge/jobs", headers=agent_headers)
    job = r.json()["job"]
    assert job and job["job_id"] == job_id
    assert job["params"]["cidr"] == "192.168.1.0/24"

    # 6. Agent submits the discovered cameras.
    cams = [{"ip": "192.168.1.10", "name": "Front Door", "is_camera": True, "confidence": 0.9}]
    r = client.post(f"/cameras/bridge/jobs/{job_id}/results",
                    headers=agent_headers, json={"cameras": cams})
    assert r.status_code == 200

    # 7. Admin reads the finished job + results.
    r = client.get(f"/cameras/bridge/scan/{job_id}")
    body = r.json()
    assert body["status"] == "done"
    assert body["results"] == cams


def test_agent_endpoints_reject_bad_token(client):
    r = client.get("/cameras/bridge/jobs",
                   headers={"X-Bridge-Id": "brg_nope", "X-Bridge-Token": "bad"})
    assert r.status_code == 401


def test_agent_endpoints_require_credentials(client):
    r = client.get("/cameras/bridge/jobs")   # no headers
    assert r.status_code == 401


def test_register_rejects_bad_code(client):
    r = client.post("/cameras/bridge/register", json={"code": "NOPE", "name": "x"})
    assert r.status_code == 400


def test_scan_offline_bridge_is_conflict(client):
    """Enqueuing a scan on a bridge that never heartbeats -> 409, not a silent hang."""
    # Register then force it stale by clearing last_seen.
    code = client.post("/cameras/bridge/pair").json()["code"]
    bridge_id = client.post("/cameras/bridge/register",
                            json={"code": code, "name": "x"}).json()["bridge_id"]
    bridge_mod._registry.get_bridge(bridge_id).last_seen = None

    r = client.post(f"/cameras/bridge/{bridge_id}/scan", json={})
    assert r.status_code == 409
