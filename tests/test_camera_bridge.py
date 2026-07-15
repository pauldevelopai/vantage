"""
Tests for the cloud-side camera-bridge protocol.

Covers the full lifecycle a "just hit scan" flow depends on:
  pairing (single-use + expiry) -> register -> auth -> heartbeat/online
  -> enqueue scan -> agent claims -> agent submits results -> console reads.

Plus the security properties: only token hashes stored, wrong token rejected,
expired/used codes rejected; and fail-safe on unknown ids.
"""

from datetime import datetime, timedelta

import pytest

from alibi.cameras.bridge import (
    BRIDGE_ONLINE_SECONDS,
    BridgeRegistry,
    _hash_token,
)


@pytest.fixture
def reg(tmp_path):
    return BridgeRegistry(storage_path=str(tmp_path / "bridges.json"))


# --- pairing --------------------------------------------------------------- #

def test_pairing_code_round_trip(reg):
    pc = reg.create_pairing_code(created_by="admin")
    assert pc.code and not pc.used_by

    creds = reg.redeem_pairing_code(pc.code, name="Home")
    assert creds and creds["bridge_id"].startswith("brg_")
    assert creds["token"]                       # plaintext returned once

    # The stored bridge holds only a HASH, never the token.
    b = reg.get_bridge(creds["bridge_id"])
    assert b.token_hash == _hash_token(creds["token"])
    assert not hasattr(b, "token")


def test_pairing_code_is_single_use(reg):
    pc = reg.create_pairing_code(created_by="admin")
    assert reg.redeem_pairing_code(pc.code, name="A") is not None
    assert reg.redeem_pairing_code(pc.code, name="B") is None   # already used


def test_pairing_code_expires(reg):
    past = datetime.utcnow() - timedelta(minutes=30)
    pc = reg.create_pairing_code(created_by="admin", now=past)   # created 30m ago (TTL 15m)
    assert reg.redeem_pairing_code(pc.code, name="Late") is None


def test_unknown_code_rejected(reg):
    assert reg.redeem_pairing_code("NOPE", name="X") is None
    assert reg.redeem_pairing_code("", name="X") is None


# --- auth ------------------------------------------------------------------ #

def test_authenticate(reg):
    creds = reg.redeem_pairing_code(reg.create_pairing_code("admin").code, name="H")
    bid, token = creds["bridge_id"], creds["token"]

    assert reg.authenticate(bid, token) is True
    assert reg.authenticate(bid, "wrong-token") is False
    assert reg.authenticate("brg_nope", token) is False
    assert reg.authenticate(bid, "") is False


# --- heartbeat / online ---------------------------------------------------- #

def test_heartbeat_and_online(reg):
    creds = reg.redeem_pairing_code(reg.create_pairing_code("admin").code, name="H")
    bid = creds["bridge_id"]

    now = datetime.utcnow()
    assert reg.heartbeat(bid, site_hint="192.168.1.0/24", now=now) is True
    assert reg.get_bridge(bid).is_online(now) is True

    stale = now + timedelta(seconds=BRIDGE_ONLINE_SECONDS + 10)
    assert reg.get_bridge(bid).is_online(stale) is False

    assert reg.heartbeat("brg_nope") is False   # fail-safe

    listed = reg.list_bridges(now)
    assert listed[0]["online"] is True
    assert "token_hash" not in listed[0]        # never leak the hash to console


# --- scan job lifecycle ---------------------------------------------------- #

def test_scan_job_full_cycle(reg):
    creds = reg.redeem_pairing_code(reg.create_pairing_code("admin").code, name="H")
    bid = creds["bridge_id"]

    # console enqueues
    job = reg.enqueue_scan(bid, params={"cidr": "192.168.1.0/24"})
    assert job.status == "pending"

    # agent claims -> running
    claimed = reg.claim_next_job(bid)
    assert claimed.job_id == job.job_id
    assert reg.get_job(job.job_id).status == "running"

    # nothing else pending
    assert reg.claim_next_job(bid) is None

    # agent submits results -> done, console reads
    cams = [{"ip": "192.168.1.10", "is_camera": True, "confidence": 0.9}]
    assert reg.submit_results(bid, job.job_id, cams) is True
    done = reg.get_job(job.job_id)
    assert done.status == "done"
    assert done.results == cams


def test_claim_is_fifo(reg):
    creds = reg.redeem_pairing_code(reg.create_pairing_code("admin").code, name="H")
    bid = creds["bridge_id"]
    base = datetime.utcnow()
    j1 = reg.enqueue_scan(bid, now=base)
    j2 = reg.enqueue_scan(bid, now=base + timedelta(seconds=1))
    assert reg.claim_next_job(bid).job_id == j1.job_id
    assert reg.claim_next_job(bid).job_id == j2.job_id


def test_submit_results_with_error(reg):
    creds = reg.redeem_pairing_code(reg.create_pairing_code("admin").code, name="H")
    bid = creds["bridge_id"]
    job = reg.enqueue_scan(bid)
    assert reg.submit_results(bid, job.job_id, [], error="scan failed on LAN") is True
    j = reg.get_job(job.job_id)
    assert j.status == "error" and j.error == "scan failed on LAN"


def test_cross_bridge_isolation(reg):
    """A bridge cannot claim or submit another bridge's jobs."""
    a = reg.redeem_pairing_code(reg.create_pairing_code("admin").code, name="A")["bridge_id"]
    b = reg.redeem_pairing_code(reg.create_pairing_code("admin").code, name="B")["bridge_id"]

    job = reg.enqueue_scan(a)
    assert reg.claim_next_job(b) is None                     # B can't see A's job
    assert reg.submit_results(b, job.job_id, [{"ip": "x"}]) is False  # B can't submit


def test_enqueue_for_unknown_bridge_is_none(reg):
    assert reg.enqueue_scan("brg_nope") is None


def test_latest_completed_scan(reg):
    bid = reg.redeem_pairing_code(reg.create_pairing_code("admin").code, name="H")["bridge_id"]
    base = datetime.utcnow()

    assert reg.latest_completed_scan(bid) is None          # nothing yet

    j1 = reg.enqueue_scan(bid, now=base)
    reg.submit_results(bid, j1.job_id, [{"ip": "1"}], now=base + timedelta(seconds=10))
    j2 = reg.enqueue_scan(bid, now=base + timedelta(seconds=20))
    reg.submit_results(bid, j2.job_id, [{"ip": "2"}], now=base + timedelta(seconds=30))
    reg.enqueue_scan(bid, now=base + timedelta(seconds=40))  # pending, ignored

    latest = reg.latest_completed_scan(bid)
    assert latest.job_id == j2.job_id                       # most recent DONE
    assert latest.results == [{"ip": "2"}]


# --- persistence ----------------------------------------------------------- #

def test_survives_reload(tmp_path):
    path = str(tmp_path / "bridges.json")
    r1 = BridgeRegistry(storage_path=path)
    creds = r1.redeem_pairing_code(r1.create_pairing_code("admin").code, name="H")
    job = r1.enqueue_scan(creds["bridge_id"])

    r2 = BridgeRegistry(storage_path=path)   # fresh load from disk
    assert r2.get_bridge(creds["bridge_id"]) is not None
    assert r2.authenticate(creds["bridge_id"], creds["token"]) is True
    assert r2.get_job(job.job_id) is not None
