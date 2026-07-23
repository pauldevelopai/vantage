"""
Hardening pass over this session's fast-written code. Each test pins a bug that
was live: a crash or a silent data loss found by reviewing the day's commits.
"""

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest


# ── ragged embeddings must not crash the gallery / classifier ────────────

def test_stack_embeddings_keeps_the_dominant_dimension_not_crash():
    from alibi.watchlist.watchlist_store import stack_embeddings
    # three 512-d and one stray 128-d — np.array would have raised
    embs = [np.ones(512) for _ in range(3)] + [np.ones(128)]
    arr = stack_embeddings(embs)
    assert arr is not None and arr.shape[1] == 512

    assert stack_embeddings([]) is None
    assert stack_embeddings([np.zeros(0)]) is None


def test_classifier_training_survives_mixed_dimensions():
    from alibi.vehicles.local_classifier import centroids_from
    ex = [("Hilux", np.ones(512)) for _ in range(3)] + [("Hilux", np.ones(128))]
    cents = centroids_from(ex)                 # must not raise
    assert "Hilux" in cents and len(cents["Hilux"]) == 512


# ── liveness must not crash on a timezone-aware timestamp ────────────────

def test_liveness_handles_an_offset_bearing_timestamp():
    from alibi.cameras import liveness as lv
    now = datetime(2026, 7, 23, 10, 0, 0)          # naive
    aware = "2026-07-23T11:59:00+02:00"            # 09:59 UTC — 1 min ago
    d = lv.describe(aware, aware, now=now)          # would TypeError before
    assert d["watching"] is True
    assert d["state"] == "live"


def test_liveness_handles_an_aware_datetime_object():
    from alibi.cameras import liveness as lv
    now = datetime(2026, 7, 23, 10, 0, 0)
    aware = datetime(2026, 7, 23, 9, 59, 0, tzinfo=timezone.utc)
    assert lv.describe(aware, aware, now=now)["watching"] is True


# ── rejections: clearing, and surviving a corrupt file ───────────────────

def test_clearing_a_rejection_lets_a_face_be_claimed_again(tmp_path):
    from alibi.watchlist import rejections as rj
    f = tmp_path / "rej.json"
    rj.record("paul", "sight-1", path=f)
    assert rj.is_rejected("paul", "sight-1", path=f)
    assert rj.clear("paul", "sight-1", path=f) is True
    assert not rj.is_rejected("paul", "sight-1", path=f)
    assert rj.clear("paul", "nope", path=f) is False


def test_rejection_writes_are_atomic(tmp_path):
    """A crash mid-write must not wipe every remembered rejection."""
    from alibi.watchlist import rejections as rj
    f = tmp_path / "rej.json"
    rj.record("paul", "a", path=f)
    rj.record("paul", "b", path=f)
    # no ".tmp-" file left behind, and both survive a reload
    assert not list(tmp_path.glob(".tmp-*"))
    assert rj.rejected_for("paul", path=f) == {"a", "b"}


# ── the atomic writer itself ─────────────────────────────────────────────

def test_atomic_write_leaves_the_old_file_intact_on_failure(tmp_path, monkeypatch):
    from alibi import atomic_json
    f = tmp_path / "x.json"
    atomic_json.write_json(f, {"good": 1})

    import json as _json
    def boom(*a, **k):
        raise RuntimeError("disk full")
    monkeypatch.setattr(atomic_json.json, "dump", boom)
    with pytest.raises(RuntimeError):
        atomic_json.write_json(f, {"new": 2})

    assert _json.loads(f.read_text()) == {"good": 1}   # untouched
    assert not list(tmp_path.glob(".tmp-*"))            # temp cleaned up


# ── ingest: a connector that raises mid-stream ends the run cleanly ──────

def test_a_connector_raising_midstream_does_not_lose_the_run(tmp_path):
    from alibi.ingest import Item, Ledger, Source, ingest

    class _Flaky:
        name = "flaky"
        def fetch(self, source, since=None):
            yield Item(external_id="1.jpg", kind="image", content=b"one")
            yield Item(external_id="2.jpg", kind="image", content=b"two")
            raise ConnectionError("stream died")

    src = Source(source_id="s", connector="flaky", basis="own_cameras",
                 authorised_by="Paul")
    r = ingest(src, _Flaky(), ledger=Ledger(path=tmp_path / "l.jsonl"))
    assert r.ingested == 2                    # kept what arrived
    assert any("stream died" in e for e in r.errors)


# ── effective_galleries cache invalidates when a backing file changes ────

def test_effective_galleries_cache_tracks_file_changes(tmp_path, monkeypatch):
    import alibi.watchlist.watchlist_store as ws
    calls = {"n": 0}
    sig = {"v": ("a",)}
    monkeypatch.setattr(ws, "_archive_signature", lambda: sig["v"])

    real = ws.WatchlistStore.get_galleries
    def counting(self):
        calls["n"] += 1
        return {}
    monkeypatch.setattr(ws.WatchlistStore, "get_galleries", counting)
    ws._EFFECTIVE_CACHE["sig"] = None
    ws._EFFECTIVE_CACHE["value"] = None

    ws.effective_galleries(); ws.effective_galleries()
    assert calls["n"] == 1                     # second call served from cache
    sig["v"] = ("b",)                          # a file changed
    ws.effective_galleries()
    assert calls["n"] == 2                     # recomputed
