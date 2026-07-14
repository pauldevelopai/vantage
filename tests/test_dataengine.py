"""
Tests for the Vantage Data Engine (§9) scaffold.

The load-bearing test class is TestPersonalDataGuard: it proves the §8
lawful-data boundary is enforced IN CODE — the engine cannot store a
people-dossier even if an upstream source starts emitting personal data.

Everything runs against fixtures — no Apify token, no network.
"""

from datetime import datetime, timedelta

import pytest

from alibi.dataengine import (
    DataDomain,
    DataEngineStore,
    LawfulBasis,
    PersonalDataRejected,
    SourceSpec,
    assert_non_personal,
    ingest_items,
    list_sources,
    run_source,
    scan_for_personal_data,
)
from alibi.dataengine.apify import ApifyClient
from alibi.dataengine.sources import get_source


@pytest.fixture
def store(tmp_path):
    return DataEngineStore(storage_path=str(tmp_path / "de.jsonl"))


# --------------------------------------------------------------------------- #
# The §8 boundary, enforced in code
# --------------------------------------------------------------------------- #

class TestPersonalDataGuard:

    def test_rejects_national_id_number(self):
        with pytest.raises(PersonalDataRejected):
            assert_non_personal({"area": "Sandton", "id_number": "8001015009087"})

    def test_rejects_id_number_by_value_even_under_innocent_key(self):
        """A 13-digit SA ID hidden under a harmless key is still caught."""
        v = scan_for_personal_data({"note": "ref 8001015009087"})
        assert any("ID number" in x for x in v)

    def test_rejects_email_and_social_profile(self):
        assert scan_for_personal_data({"contact": "jan@example.com"})
        assert scan_for_personal_data({"link": "https://facebook.com/someone"})
        assert scan_for_personal_data({"link": "https://linkedin.com/in/someone"})

    def test_rejects_person_name_and_dob_and_biometrics(self):
        for payload in (
            {"surname": "Botha"},
            {"first_name": "Jan"},
            {"date_of_birth": "1980-01-01"},
            {"face_embedding": [0.1, 0.2]},
            {"criminal_record": "x"},
            {"owner_name": "Jan Botha"},
        ):
            assert scan_for_personal_data(payload), f"should reject {payload}"

    def test_rejects_personal_data_nested_deep(self):
        payload = {"area": "CBD", "meta": {"contributors": [{"surname": "Botha"}]}}
        assert scan_for_personal_data(payload)

    def test_allows_place_fields(self):
        """A PLACE legitimately has a name, address and phone — not personal."""
        assert_non_personal({
            "place_name": "Sandton Police Station",
            "address": "Corner Rivonia Rd",
            "phone": "011 722 4200",
            "latitude": -26.1,
            "longitude": 28.05,
        })  # must not raise

    def test_allows_vehicle_reference_fields(self):
        assert_non_personal({
            "make": "Toyota", "model": "Quantum", "body_type": "minibus",
            "common_colors": ["white"],
        })  # must not raise


# --------------------------------------------------------------------------- #
# Ingest pipeline: normalise (allowlist) -> guard -> tag -> store
# --------------------------------------------------------------------------- #

class TestIngestPipeline:

    def test_ingests_and_tags_places_data(self, store):
        spec = get_source("places.area_crime_stats")
        items = [
            {"area": "Sandton", "period": "2026Q1", "crime_category": "vehicle theft",
             "count": 42, "source_url": "https://example.gov/stats"},
            {"area": "Rosebank", "period": "2026Q1", "crime_category": "vehicle theft",
             "count": 17, "source_url": "https://example.gov/stats"},
        ]

        result = ingest_items(spec, items, store)

        assert result.fetched == 2
        assert result.stored == 2
        assert result.rejected_personal == 0

        recs = store.query(source_id="places.area_crime_stats")
        assert len(recs) == 2
        r = recs[0]
        # Tagged by construction
        assert r.domain == DataDomain.PLACES_CONTEXT
        assert r.lawful_basis == LawfulBasis.PUBLIC_INTEREST_STATISTICS
        assert r.retention_until > r.ingested_at
        assert r.provenance["source_id"] == "places.area_crime_stats"
        assert r.provenance["source_url"] == "https://example.gov/stats"

    def test_allowlist_drops_undeclared_fields(self, store):
        """An actor that suddenly emits a personal field loses it at normalisation."""
        spec = get_source("places.area_crime_stats")
        items = [{
            "area": "Sandton", "count": 42,
            "reporter_surname": "Botha",          # undeclared -> dropped
            "reporter_id_number": "8001015009087",  # undeclared -> dropped
        }]

        result = ingest_items(spec, items, store)

        assert result.stored == 1
        payload = store.query()[0].payload
        assert "reporter_surname" not in payload
        assert "reporter_id_number" not in payload
        assert payload["area"] == "Sandton"

    def test_guard_blocks_personal_data_that_survives_normalisation(self, store):
        """A mis-declared source (passthrough normaliser) is still fail-closed."""
        bad_spec = SourceSpec(
            source_id="places.bad_passthrough",
            domain=DataDomain.PLACES_CONTEXT,
            lawful_basis=LawfulBasis.LEGITIMATE_INTEREST_NON_PERSONAL,
            retention_days=30,
            description="Mis-declared source with no allowlist",
            normaliser=None,  # passthrough — no allowlist protection
        )
        items = [{"area": "Sandton", "surname": "Botha", "id_number": "8001015009087"}]

        result = ingest_items(bad_spec, items, store)

        assert result.stored == 0
        assert result.rejected_personal == 1
        assert result.rejections  # violations reported, not swallowed
        assert store.query() == []  # nothing reached the store

    def test_skips_incomplete_items(self, store):
        spec = get_source("places.area_crime_stats")
        result = ingest_items(spec, [{"period": "2026Q1"}], store)  # no area/count
        assert result.stored == 0
        assert result.skipped == 1

    def test_reruns_do_not_duplicate(self, store):
        spec = get_source("reference.vehicle_models")
        items = [{"make": "Toyota", "model": "Quantum"}]
        ingest_items(spec, items, store)
        ingest_items(spec, items, store)  # same content again
        ids = {r.record_id for r in store.query()}
        assert len(ids) == 1  # stable content-hash id


# --------------------------------------------------------------------------- #
# Retention + honest empty states
# --------------------------------------------------------------------------- #

class TestRetention:

    def test_expired_records_are_not_returned(self, store):
        spec = get_source("places.poi")
        past = datetime.utcnow() - timedelta(days=400)  # retention is 180d
        ingest_items(spec, [{"place_name": "Old Station"}], store, now=past)

        assert store.query() == []                       # enforced on read
        assert len(store.query(include_expired=True)) == 1

    def test_prune_removes_expired(self, store):
        spec = get_source("places.poi")
        past = datetime.utcnow() - timedelta(days=400)
        ingest_items(spec, [{"place_name": "Old Station"}], store, now=past)
        ingest_items(spec, [{"place_name": "New Station"}], store)

        removed = store.prune()
        assert removed == 1
        remaining = store.query(include_expired=True)
        assert len(remaining) == 1
        assert remaining[0].payload["place_name"] == "New Station"

    def test_empty_store_is_honest(self, store):
        """No data -> empty list. Never fabricated content (no-fake-data rule)."""
        assert store.query() == []
        assert store.stats()["total_live_records"] == 0


# --------------------------------------------------------------------------- #
# Registry + fail-safe
# --------------------------------------------------------------------------- #

class TestRegistryAndFailSafe:

    def test_registered_sources_are_only_lawful_domains(self):
        specs = list_sources()
        assert specs
        for s in specs:
            assert s.domain in (DataDomain.PLACES_CONTEXT, DataDomain.DETECTION_REFERENCE)
            assert s.retention_days > 0      # everything expires
            assert s.lawful_basis is not None

    def test_source_must_have_positive_retention(self):
        with pytest.raises(ValueError):
            SourceSpec(
                source_id="x", domain=DataDomain.PLACES_CONTEXT,
                lawful_basis=LawfulBasis.OFFICIAL_REGISTRY,
                retention_days=0, description="never expires",
            )

    def test_run_source_without_token_is_honest_not_fabricated(self, store, monkeypatch):
        monkeypatch.delenv("APIFY_TOKEN", raising=False)
        result = run_source("places.poi", store=store, client=ApifyClient(token=None))
        assert result.stored == 0
        assert result.error  # says why, rather than inventing data
        assert store.query() == []

    def test_unknown_source_is_reported(self, store):
        result = run_source("nope.not_a_source", store=store)
        assert result.error and "unknown source" in result.error
