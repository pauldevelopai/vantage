"""Vehicle review queue + local-data loop — pinned honesty + correctness."""

from datetime import datetime

import pytest

from alibi.vehicles import review_queue as rq

NOW = datetime(2026, 7, 18, 12, 0, 0)


def test_build_item_needs_a_usable_crop():
    assert rq.build_review_item("cam", "", [1, 2, 3, 4], {}) is None       # no frame
    assert rq.build_review_item("cam", "/f.jpg", [1, 2, 0, 4], {}) is None  # zero-w bbox
    assert rq.build_review_item("cam", "/f.jpg", "bad", {}) is None         # bad bbox


def test_build_item_keeps_claim_verbatim():
    it = rq.build_review_item("cam", "/api/cameras/frames/x.jpg", [10, 20, 30, 40],
                              {"colour": "white", "make": "Toyota", "model": "Fortuner",
                               "body": "SUV", "confidence": "high", "junk": 1}, now=NOW)
    assert it.status == "pending" and it.label is None
    assert it.claimed == {"colour": "white", "make": "Toyota", "model": "Fortuner",
                          "body": "SUV", "confidence": "high"}


def test_confirm_accepts_claim_as_label_or_correction():
    it = rq.build_review_item("cam", "/f.jpg", [1, 2, 3, 4],
                              {"make": "Toyota", "model": "Fortuner", "colour": "white"}, now=NOW)
    rq.apply_review(it, "confirm", "admin", now=NOW)
    assert it.status == "confirmed" and it.label["make"] == "Toyota"
    # a correction overrides the claim
    it2 = rq.build_review_item("cam", "/f.jpg", [1, 2, 3, 4], {"make": "Ford"}, now=NOW)
    rq.apply_review(it2, "confirm", "admin", label={"make": "Toyota", "model": "Hilux"}, now=NOW)
    assert it2.label["make"] == "Toyota" and it2.label["model"] == "Hilux"


def test_reject_clears_label():
    it = rq.build_review_item("cam", "/f.jpg", [1, 2, 3, 4], {"make": "X"}, now=NOW)
    rq.apply_review(it, "reject", "admin", now=NOW)
    assert it.status == "rejected" and it.label is None


def test_store_roundtrip_pending_counts_and_corpus(tmp_path):
    store = rq.ReviewQueueStore(storage_path=str(tmp_path / "rq.jsonl"))
    a = rq.build_review_item("cam", "/a.jpg", [1, 2, 3, 4], {"make": "Toyota", "model": "Hilux", "colour": "white"}, now=NOW)
    b = rq.build_review_item("cam", "/b.jpg", [1, 2, 3, 4], {"make": "Ford"}, now=NOW)
    store.add(a); store.add(b)
    assert len(store.list_pending()) == 2
    # confirm one -> corpus has it, pending drops
    rq.apply_review(a, "confirm", "admin", now=NOW)
    store.update(a)
    assert store.counts() == {"pending": 1, "confirmed": 1, "rejected": 0}
    corpus = store.confirmed_labels()
    assert len(corpus) == 1 and corpus[0]["label"]["model"] == "Hilux"


def test_enqueue_only_on_unambiguous_pairing(tmp_path, monkeypatch):
    store = rq.ReviewQueueStore(storage_path=str(tmp_path / "rq.jsonl"))
    monkeypatch.setattr(rq, "get_review_queue_store", lambda: store)
    one = {"detections": [{"class": "car", "bbox": [1, 2, 30, 40]}]}
    assert rq.enqueue_vehicle_guess(one, [{"make": "Toyota"}], "cam", "f1", now=NOW) == 1
    # two vehicles, one description -> ambiguous -> nothing enqueued
    two = {"detections": [{"class": "car", "bbox": [1, 2, 3, 4]}, {"class": "truck", "bbox": [5, 6, 7, 8]}]}
    assert rq.enqueue_vehicle_guess(two, [{"make": "Toyota"}], "cam", "f2", now=NOW) == 0
    assert len(store.list_pending()) == 1
