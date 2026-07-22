"""
The ingestion core. Pinned on the two things that matter at scale.

A pipeline built to bring in millions of items cheaply is exactly where an
unlawful import becomes easy and invisible, so provenance is enforced at
construction rather than checked politely later. And deduplication must be by
CONTENT — the same photograph from two sources is one item that keeps both
authorities, because removing one licence must not silently strip the basis of
a copy that had its own.
"""

import pytest

from alibi.ingest import Item, Ledger, ProvenanceError, Source, content_key, ingest
from alibi.ingest.connectors import filesystem  # noqa: F401 — registers it
from alibi.ingest.registry import available, get


def _src(**kw):
    base = dict(source_id="s", connector="filesystem", basis="own_cameras",
                authorised_by="Paul")
    base.update(kw)
    return Source(**base)


class _Fake:
    name = "fake"

    def __init__(self, items):
        self.items = items

    def fetch(self, source, since=None):
        yield from self.items


# ── provenance is a precondition, not a label ────────────────────────────

def test_a_source_without_a_lawful_basis_cannot_exist():
    with pytest.raises(ProvenanceError):
        Source(source_id="x", connector="fake", basis="", authorised_by="Paul")
    with pytest.raises(ProvenanceError):
        Source(source_id="x", connector="fake", basis="scraped", authorised_by="Paul")


def test_someone_must_take_responsibility():
    with pytest.raises(ProvenanceError):
        Source(source_id="x", connector="fake", basis="own_cameras", authorised_by="  ")


def test_a_licence_must_be_named_to_be_honoured():
    with pytest.raises(ProvenanceError):
        Source(source_id="x", connector="fake", basis="licensed", authorised_by="Paul")
    ok = Source(source_id="x", connector="fake", basis="licensed",
                authorised_by="Paul", licence="CC BY-NC 4.0")
    assert ok.stamp()["licence"] == "CC BY-NC 4.0"


def test_material_with_people_needs_a_basis_that_permits_people():
    """The guard that matters. A public-domain or licensed dataset is not a
    lawful basis for importing identifiable people into a security system."""
    for basis in ("public_domain", "licensed"):
        with pytest.raises(ProvenanceError):
            Source(source_id="x", connector="fake", basis=basis, authorised_by="Paul",
                   licence="X", contains_people=True)
    assert _src(contains_people=True).contains_people is True


# ── deduplication, provenance, resilience ────────────────────────────────

def test_identical_bytes_are_one_item_however_they_are_named():
    a = Item(external_id="a.jpg", kind="image", content=b"same")
    b = Item(external_id="deep/other-name.jpg", kind="image", content=b"same")
    assert content_key(a) == content_key(b)


def test_the_same_picture_from_two_sources_keeps_both_authorities(tmp_path):
    """Removing one licence must not silently strip the basis of a copy that
    arrived under its own."""
    led = Ledger(path=tmp_path / "ledger.jsonl")
    item = Item(external_id="x.jpg", kind="image", content=b"pic")
    ingest(_src(source_id="cameras"), _Fake([item]), ledger=led)
    ingest(Source(source_id="dataset", connector="fake", basis="licensed",
                  authorised_by="Paul", licence="CC BY 4.0"), _Fake([item]), ledger=led)

    prov = led.provenance(content_key(item))
    assert {p["source_id"] for p in prov} == {"cameras", "dataset"}


def test_a_second_run_ingests_nothing_new(tmp_path):
    led = Ledger(path=tmp_path / "ledger.jsonl")
    items = [Item(external_id=f"{i}.jpg", kind="image", content=f"pic{i}".encode())
             for i in range(5)]
    first = ingest(_src(), _Fake(items), ledger=led)
    second = ingest(_src(), _Fake(items), ledger=led)
    assert first.ingested == 5 and first.duplicates == 0
    assert second.ingested == 0 and second.duplicates == 5


def test_one_bad_item_does_not_take_the_run_down(tmp_path):
    """At a million items, a run that dies on a bad file is not a pipeline."""
    led = Ledger(path=tmp_path / "ledger.jsonl")
    good = [Item(external_id=f"{i}.jpg", kind="image", content=f"p{i}".encode())
            for i in range(3)]

    def boom(item):
        if item.external_id == "1.jpg":
            raise ValueError("corrupt")
        return [0.0]

    r = ingest(_src(), _Fake(good), embed=boom, ledger=led)
    assert r.ingested == 2 and r.failed == 1
    assert "corrupt" in r.errors[0]


def test_every_indexed_record_carries_its_provenance(tmp_path):
    led = Ledger(path=tmp_path / "ledger.jsonl")
    seen = []
    ingest(_src(), _Fake([Item(external_id="a.jpg", kind="image", content=b"z")]),
           index=lambda key, item, source, vec: seen.append(source.stamp()),
           ledger=led)
    assert seen[0]["authorised_by"] == "Paul"
    assert seen[0]["basis"] == "own_cameras"


# ── the modular seam ─────────────────────────────────────────────────────

def test_a_connector_is_one_method_and_a_registry_entry():
    assert "filesystem" in available()
    assert hasattr(get("filesystem"), "fetch")


def test_the_filesystem_connector_reads_a_directory(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "a.jpg").write_bytes(b"one")
    (tmp_path / "sub" / "b.png").write_bytes(b"two")
    (tmp_path / "notes.txt").write_text("ignored")

    src = _src(config={"path": str(tmp_path)})
    items = list(get("filesystem").fetch(src))
    assert {i.external_id for i in items} == {"a.jpg", "sub/b.png"}
    assert all(i.content for i in items)
