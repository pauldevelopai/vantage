"""
Tests for the Vantage Bridge agent (the thing that runs on the user's network).

The agent must be self-contained (no Vantage imports) so it runs as one file,
and its poll->scan->report loop must behave. HTTP is mocked; no real network.

Also tests the personalized-download endpoint bakes in the URL + pairing code.
"""

import ast

import pytest

from alibi.cameras import bridge_agent as agent


# --- the agent must be a standalone single file ---------------------------- #

def test_agent_has_no_vantage_imports():
    """It's shipped as one downloadable file — it can't import the alibi package."""
    tree = ast.parse(open(agent.__file__).read())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert not (node.module or "").startswith("alibi")
        if isinstance(node, ast.Import):
            assert not any(a.name.startswith("alibi") for a in node.names)


# --- pure helpers ---------------------------------------------------------- #

def test_vendor_and_rtsp_helpers():
    assert agent.vendor_for_mac("44:19:B6:00:00:01") == "Hikvision"
    assert agent.vendor_for_mac(None) is None
    assert agent.parse_rtsp_options("RTSP/1.0 200 OK\r\nServer: Cam\r\n") == (True, "Cam")
    assert agent.parse_rtsp_options("HTTP/1.1 404\r\n")[0] is False


# --- scan() output shape (strategies mocked) ------------------------------- #

def test_scan_produces_console_shape(monkeypatch):
    monkeypatch.setattr(agent, "ws_discover", lambda timeout=4.0: {
        "192.168.1.10": {"name": "Front Door"}})
    monkeypatch.setattr(agent, "sweep", lambda subnet=None: {
        "192.168.1.10": [80, 554], "192.168.1.30": [80]})
    monkeypatch.setattr(agent, "rtsp_probe",
                        lambda ip, port=554, timeout=2.5: (ip == "192.168.1.10", "x"))
    monkeypatch.setattr(agent, "read_arp", lambda: {"192.168.1.10": "44:19:b6:00:00:01"})

    out = agent.scan()
    top = out[0]
    # camera-first ordering + the keys the console renders
    assert top["ip"] == "192.168.1.10" and top["is_camera"] is True
    assert top["vendor"] == "Hikvision" and top["rtsp_confirmed"] is True
    for k in ("ip", "port", "rtsp_url", "confidence", "is_camera", "open_ports"):
        assert k in top
    # http-only host with no rtsp is not a camera
    assert out[-1]["ip"] == "192.168.1.30" and out[-1]["is_camera"] is False


# --- register + poll loop (HTTP mocked) ------------------------------------ #

class _FakeHttp:
    def __init__(self):
        self.calls = []
        self.job = None

    def __call__(self, method, path, body=None, headers=None, timeout=30):
        self.calls.append((method, path, body))
        if path == "/api/cameras/bridge/register":
            return 200, {"bridge_id": "brg_1", "token": "tok"}
        if path == "/api/cameras/bridge/jobs":
            return 200, {"job": self.job}
        return 200, {"status": "ok"}


def test_register_saves_creds(monkeypatch, tmp_path):
    fake = _FakeHttp()
    monkeypatch.setattr(agent, "_http", fake)
    monkeypatch.setattr(agent, "CRED_FILE", str(tmp_path / "creds.json"))
    monkeypatch.setattr(agent, "local_subnet", lambda: "192.168.1.0/24")

    creds = agent.register("ABCD1234")
    assert creds == {"bridge_id": "brg_1", "token": "tok"}
    assert agent.load_creds() == creds                 # persisted
    # the register call carried the code + a site hint
    reg = [c for c in fake.calls if c[1].endswith("/register")][0]
    assert reg[2]["code"] == "ABCD1234"


def test_poll_once_runs_scan_and_reports(monkeypatch):
    fake = _FakeHttp()
    fake.job = {"job_id": "job_1", "params": {"cidr": "192.168.1.0/24"}}
    monkeypatch.setattr(agent, "_http", fake)
    monkeypatch.setattr(agent, "scan",
                        lambda cidr=None: [{"ip": "192.168.1.10", "is_camera": True}])

    result = agent.poll_once({"X-Bridge-Id": "brg_1", "X-Bridge-Token": "tok"})
    assert result == "scanned"
    posted = [c for c in fake.calls if "results" in c[1]][0]
    assert posted[1] == "/api/cameras/bridge/jobs/job_1/results"
    assert posted[2]["cameras"][0]["ip"] == "192.168.1.10"


def test_poll_once_idle_heartbeats(monkeypatch):
    fake = _FakeHttp()          # job is None
    monkeypatch.setattr(agent, "_http", fake)
    monkeypatch.setattr(agent, "local_subnet", lambda: "10.0.0.0/24")
    assert agent.poll_once({}) == "idle"
    assert any("heartbeat" in c[1] for c in fake.calls)


def test_poll_once_unauthorized(monkeypatch):
    monkeypatch.setattr(agent, "_http", lambda *a, **k: (401, {}))
    assert agent.poll_once({}) == "unauthorized"


def test_scan_failure_reports_error(monkeypatch):
    fake = _FakeHttp()
    fake.job = {"job_id": "job_x", "params": {}}
    monkeypatch.setattr(agent, "_http", fake)

    def boom(cidr=None):
        raise RuntimeError("nic down")
    monkeypatch.setattr(agent, "scan", boom)

    assert agent.poll_once({}) == "scanned"    # still completes the cycle
    posted = [c for c in fake.calls if "results" in c[1]][0]
    assert posted[2]["error"] == "nic down" and posted[2]["cameras"] == []


# --- personalized download endpoint ---------------------------------------- #

@pytest.fixture
def client(tmp_path):
    from fastapi.testclient import TestClient
    import alibi.cameras.bridge as bridge_mod
    from alibi.cameras.bridge import BridgeRegistry
    from alibi.alibi_api import app
    from alibi.auth import get_current_user, User, Role

    bridge_mod._registry = BridgeRegistry(storage_path=str(tmp_path / "b.json"))
    admin = User(username="admin", password_hash="x", role=Role.ADMIN, full_name="A")
    app.dependency_overrides[get_current_user] = lambda: admin
    yield TestClient(app)
    app.dependency_overrides.clear()
    bridge_mod._registry = None


def test_download_is_personalized_runnable_python(client):
    r = client.get("/cameras/bridge/download")
    assert r.status_code == 200
    assert "attachment" in r.headers.get("content-disposition", "")
    body = r.text

    # It's valid Python and self-contained.
    ast.parse(body)
    assert "import alibi" not in body

    # A pairing code was baked in (not the empty default), and the URL points back.
    m = __import__("re").search(r'PAIRING_CODE = os.environ.get\("VANTAGE_PAIRING_CODE", "([^"]+)"\)', body)
    assert m and m.group(1)                     # non-empty code
    assert 'VANTAGE_URL = os.environ.get("VANTAGE_URL", "http' in body

    # The baked code is real — it exists in the registry as an unused pairing code.
    import alibi.cameras.bridge as bridge_mod
    assert bridge_mod.get_bridge_registry().redeem_pairing_code(m.group(1), name="x") is not None
