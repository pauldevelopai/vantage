"""
Tests the wired POI source against a REAL captured Apify response.

`tests/fixtures/apify_google_places_sample.json` is an actual
compass/crawler-google-places item (Saps Sandton Police Station), captured with
reviews/personal-data collection disabled. No mock data — real shape, real keys.

What these prove:
  * The normaliser maps the actor's real 57-key item to our 10-field canonical
    payload (allowlist: everything undeclared is dropped).
  * The guard passes it — a PLACE's name/address/phone are not personal data.
  * The ingested record is tagged + cited, and feeds area context for "Sandton".
"""

import json
from pathlib import Path

import pytest

from alibi.dataengine import DataEngineStore, ingest_items
from alibi.dataengine.context import get_area_context
from alibi.dataengine.guard import scan_for_personal_data
from alibi.dataengine.sources import get_source, normalise_poi

FIXTURE = Path(__file__).parent / "fixtures" / "apify_google_places_sample.json"


@pytest.fixture
def raw_items():
    return json.loads(FIXTURE.read_text())


@pytest.fixture
def store(tmp_path):
    return DataEngineStore(storage_path=str(tmp_path / "de.jsonl"))


def test_fixture_is_the_real_actor_shape(raw_items):
    item = raw_items[0]
    assert item["title"] == "Saps Sandton Police Station"
    assert item["categoryName"] == "State police"
    assert item["city"] == "Sandton"
    assert item["location"]["lat"] and item["location"]["lng"]
    assert len(item.keys()) > 40  # the actor really does emit a lot of fields


def test_normaliser_maps_real_item_and_drops_the_rest(raw_items):
    payload = normalise_poi(raw_items[0])

    assert payload["place_name"] == "Saps Sandton Police Station"
    assert payload["category"] == "State police"
    assert payload["area"] == "Sandton"          # what camera.area matches on
    assert payload["neighborhood"] == "Morningside"
    assert payload["latitude"] == pytest.approx(-26.08, abs=0.01)
    assert payload["source_url"].startswith("https://www.google.com/maps")

    # Allowlist: the actor's other ~47 fields are gone.
    raw_keys = set(raw_items[0].keys())
    kept = set(payload.keys())
    assert len(kept) <= 11
    for dropped in ("popularTimesHistogram", "reviewsTags", "peopleAlsoSearch",
                    "imageUrl", "placeId", "cid", "website"):
        assert dropped in raw_keys       # the actor did send it
        assert dropped not in kept       # we did not keep it

    # `website` is excluded on purpose: for many businesses it is a Facebook
    # page, which would (correctly) trip the social-URL guard.
    assert "website" not in payload


def test_real_item_passes_the_personal_data_guard(raw_items):
    """A police station's name, address and phone are a PLACE, not a person."""
    payload = normalise_poi(raw_items[0])
    assert scan_for_personal_data(payload) == []


def test_end_to_end_ingest_tags_and_cites(raw_items, store):
    spec = get_source("places.poi")
    result = ingest_items(spec, raw_items, store)

    assert result.stored == 1
    assert result.rejected_personal == 0

    rec = store.query()[0]
    assert rec.source_id == "places.poi"
    assert rec.lawful_basis.value == "legitimate_interest_non_personal"
    assert rec.retention_until > rec.ingested_at
    assert rec.provenance["apify_actor"] == "compass/crawler-google-places"
    assert rec.provenance["source_url"].startswith("https://www.google.com/maps")


def test_feeds_area_context_for_sandton(raw_items, store):
    """The whole point: a Sandton camera now gets real, cited area background."""
    ingest_items(get_source("places.poi"), raw_items, store)

    ctx = get_area_context("Sandton", store=store)

    assert not ctx.is_empty()
    poi = next(i for i in ctx.items if i.kind == "poi")
    assert "Saps Sandton Police Station" in poi.detail
    assert poi.citation["source_id"] == "places.poi"
    assert poi.citation["source_url"]
    # And it still carries the rule that keeps it out of the "reasons".
    assert "not evidence about the detected person" in ctx.render_for_prompt().lower()


def test_actor_input_does_not_collect_personal_data():
    """The source declaration must not fetch reviews/reviewer names at all."""
    spec = get_source("places.poi")
    assert spec.apify_actor == "compass/crawler-google-places"
    assert spec.actor_input["maxReviews"] == 0
    assert spec.actor_input["scrapeReviewerName"] is False
    assert spec.actor_input["scrapeReviewsPersonalData"] is False


def test_context_matches_via_query_area_when_city_is_the_metro(store):
    """Google's `city` for a Somerset West clinic is "Cape Town" (observed
    live 2026-07-15) — the camera's area must still find the record via the
    ingest-stamped `query_area`."""
    from alibi.dataengine.ingest import ingest_items as _ingest

    item = {
        "title": "SAPS Somerset West Police Station",
        "city": "Cape Town",
        "categoryName": "State police",
        "neighborhood": "Somerset West",
    }
    _ingest(get_source("places.poi"), [item], store,
            payload_extra={"query_area": "Somerset West"})

    ctx = get_area_context("Somerset West", store=store)
    assert not ctx.is_empty()
    assert "SAPS Somerset West Police Station" in ctx.items[0].detail

    # The stamp passed the guard like everything else — and an unrelated area
    # still gets an honest empty state, not someone else's places.
    assert get_area_context("Windhoek", store=store).is_empty()
