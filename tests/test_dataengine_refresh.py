"""
Tests for the scheduled data-engine refresh (§9).

The behaviour that most needs proving is COST CONTROL — Apify bills per result
and the account may be on a small monthly credit:

  * only areas that have cameras are ever fetched;
  * fresh areas are skipped (no re-fetching what we already hold);
  * a hard cap defers the rest, and says so (never a silent truncation);
  * --dry-run spends nothing.

Plus: prune always runs, and a missing token degrades honestly.
"""

from datetime import datetime, timedelta

import pytest

from alibi.dataengine import DataEngineStore, ingest_items
from alibi.dataengine.refresh import (
    RefreshReport,
    areas_from_cameras,
    main,
    needs_refresh,
    refresh,
)
from alibi.dataengine.sources import get_source


@pytest.fixture
def store(tmp_path):
    return DataEngineStore(storage_path=str(tmp_path / "de.jsonl"))


class _FakeClient:
    """Stands in for Apify — records what it was asked to fetch."""

    def __init__(self, items=None):
        self.calls = []
        self._items = items if items is not None else [
            {"title": "Saps Station", "city": "Sandton", "categoryName": "State police"}
        ]

    def available(self):
        return True

    def run_actor_sync(self, actor, actor_input=None):
        self.calls.append((actor, actor_input))
        return list(self._items)


def _seed(store, area, when=None):
    ingest_items(
        get_source("places.poi"),
        [{"title": f"Station {area}", "city": area, "categoryName": "State police"}],
        store,
        now=when,
    )


class TestFreshnessGate:

    def test_area_with_no_data_needs_refresh(self, store):
        assert needs_refresh("Sandton", store) is True

    def test_freshly_ingested_area_is_skipped(self, store):
        _seed(store, "Sandton")
        assert needs_refresh("Sandton", store, min_age_days=30) is False

    def test_stale_area_needs_refresh(self, store):
        _seed(store, "Sandton", when=datetime.utcnow() - timedelta(days=45))
        assert needs_refresh("Sandton", store, min_age_days=30) is True


class TestCostControl:

    def test_only_fetches_areas_that_need_it(self, store):
        _seed(store, "Sandton")                      # fresh -> skip
        client = _FakeClient()

        report = refresh(store=store, client=client,
                         areas=["Sandton", "Rosebank"], min_age_days=30)

        assert report.areas_skipped_fresh == ["Sandton"]
        assert report.areas_refreshed == ["Rosebank"]
        assert len(client.calls) == 1                # Sandton never fetched

    def test_budget_cap_defers_and_reports(self, store):
        client = _FakeClient()
        report = refresh(store=store, client=client,
                         areas=["A", "B", "C", "D"], max_areas=2)

        assert len(report.areas_refreshed) == 2
        # Deferred, not silently dropped.
        assert report.areas_over_budget == ["C", "D"]
        assert len(client.calls) == 2

    def test_dry_run_spends_nothing(self, store):
        client = _FakeClient()
        report = refresh(store=store, client=client,
                         areas=["Sandton"], dry_run=True)

        assert report.dry_run is True
        assert report.areas_refreshed == ["Sandton"]  # what WOULD run
        assert client.calls == []                     # but nothing was fetched
        assert report.stored == 0
        assert store.query() == []                    # nothing written

    def test_max_places_is_passed_through(self, store):
        client = _FakeClient()
        refresh(store=store, client=client, areas=["Sandton"], max_places=7)
        _, actor_input = client.calls[0]
        assert actor_input["maxCrawledPlacesPerSearch"] == 7

    def test_personal_data_collection_stays_off_on_scheduled_runs(self, store):
        """The declaration's safety input must survive the per-run override."""
        client = _FakeClient()
        refresh(store=store, client=client, areas=["Sandton"])
        _, actor_input = client.calls[0]
        assert actor_input["maxReviews"] == 0
        assert actor_input["scrapeReviewerName"] is False
        assert actor_input["scrapeReviewsPersonalData"] is False


class TestAreasFromCameras:

    def test_no_cameras_means_no_areas(self, monkeypatch):
        """Honest empty state — we do not go scrape the world."""
        monkeypatch.setattr(
            "alibi.cameras.camera_store.get_camera_store",
            lambda: type("S", (), {"list_all": lambda self: []})(),
        )
        assert areas_from_cameras() == []

    def test_dedupes_areas_case_insensitively(self, monkeypatch):
        cams = [
            type("C", (), {"area": "Sandton"})(),
            type("C", (), {"area": "sandton"})(),
            type("C", (), {"area": "Rosebank"})(),
            type("C", (), {"area": ""})(),      # unset -> ignored
        ]
        monkeypatch.setattr(
            "alibi.cameras.camera_store.get_camera_store",
            lambda: type("S", (), {"list_all": lambda self: cams})(),
        )
        assert areas_from_cameras() == ["Rosebank", "Sandton"]


class TestPruneAndFailSafe:

    def test_prune_runs_and_removes_expired(self, store):
        _seed(store, "Old", when=datetime.utcnow() - timedelta(days=400))  # retention 180d
        client = _FakeClient()

        report = refresh(store=store, client=client, areas=[])

        assert report.pruned == 1
        assert store.query(include_expired=True) == []

    def test_missing_token_degrades_honestly(self, store, monkeypatch):
        monkeypatch.delenv("APIFY_TOKEN", raising=False)
        from alibi.dataengine.apify import ApifyClient

        report = refresh(store=store, client=ApifyClient(token=None), areas=["Sandton"])

        assert report.stored == 0
        assert report.errors            # says why
        assert store.query() == []      # nothing invented

    def test_fetch_error_does_not_raise(self, store):
        class Boom:
            def available(self): return True
            def run_actor_sync(self, *a, **k): raise RuntimeError("apify down")

        report = refresh(store=store, client=Boom(), areas=["Sandton"])
        assert report.errors
        assert report.stored == 0


class TestCli:

    def test_dry_run_cli_exits_clean(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(
            "alibi.cameras.camera_store.get_camera_store",
            lambda: type("S", (), {"list_all": lambda self: []})(),
        )
        code = main(["--dry-run"])
        out = capsys.readouterr().out
        assert code == 0
        assert "DRY RUN" in out
        assert "no camera has an area set" in out


class TestGeoAnchoredQuery:
    """The area anchors WHERE to search; it is not a keyword.

    Observed live 2026-07-15: "police station Somerset West" keyword-matched
    station NAMES worldwide (St. Louis, New Jersey, Utah) — billed junk. The
    area must go in `locationQuery`, with generic search terms.
    """

    def test_run_poi_sends_location_query_not_keyword_searches(self, store):
        from alibi.dataengine.ingest import POI_SEARCH_TERMS, run_poi_for_area

        client = _FakeClient()
        run_poi_for_area("Somerset West", store=store, client=client)

        _, actor_input = client.calls[0]
        assert actor_input["locationQuery"] == "Somerset West"
        assert actor_input["searchStringsArray"] == POI_SEARCH_TERMS
        # Emergency response comes first, and no term embeds the area (that is
        # what caused the worldwide keyword drift).
        assert POI_SEARCH_TERMS[:3] == ["police station", "hospital", "fire station"]
        assert all("somerset" not in t.lower() for t in actor_input["searchStringsArray"])
        # And the safety-relevant input still can't collect personal data.
        assert actor_input["maxReviews"] == 0
        assert actor_input["scrapeReviewerName"] is False

    def test_stored_records_carry_the_queried_area(self, store):
        from alibi.dataengine.ingest import run_poi_for_area

        # Google reports the metro as `city` — the record must still be
        # attributable to the area we queried for.
        client = _FakeClient(items=[{
            "title": "SAPS Somerset West Police Station",
            "city": "Cape Town",
            "categoryName": "State police",
        }])
        run_poi_for_area("Somerset West", store=store, client=client)

        rec = store.query()[0]
        assert rec.payload["query_area"] == "Somerset West"
        assert rec.payload["area"] == "Cape Town"   # Google's city, kept honestly

    def test_freshness_gate_matches_on_query_area(self, store):
        """Metro-city records must not make their area look permanently stale
        (that would re-fetch — and re-bill — every single run)."""
        from alibi.dataengine.ingest import run_poi_for_area

        client = _FakeClient(items=[{
            "title": "SAPS Somerset West Police Station",
            "city": "Cape Town",
            "categoryName": "State police",
        }])
        run_poi_for_area("Somerset West", store=store, client=client)

        assert needs_refresh("Somerset West", store, min_age_days=30) is False
        assert needs_refresh("Stellenbosch", store, min_age_days=30) is True
