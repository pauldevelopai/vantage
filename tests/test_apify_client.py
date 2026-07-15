"""
Tests the Apify client's start-and-poll transport (§9).

Why this transport exists: the Google Places actor routinely runs 2-5 minutes.
The old run-sync call sat on one HTTP request with a 120s read timeout — the
client gave up while Apify kept running (and billing) the actor, and the
results were lost. These tests pin the behaviours that prevent that:

  * a run that finishes after several polls still returns its items;
  * a run that ends in anything but SUCCEEDED returns None (never raises);
  * a run that outlives the deadline is ABORTED so it stops spending credit.

All HTTP is faked at the `requests` boundary — no network, no token spend.
"""

from typing import Any, Dict, List, Optional

import pytest

from alibi.dataengine import apify as apify_mod
from alibi.dataengine.apify import ApifyClient


class FakeResponse:
    def __init__(self, payload: Any, status: int = 200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class FakeApifyAPI:
    """Simulates POST /acts/{id}/runs, GET /actor-runs/{id}, GET /datasets/{id}/items."""

    def __init__(self, statuses: List[str], items: Optional[List[Dict]] = None):
        self.statuses = list(statuses)  # consumed one per status poll
        self.items = items if items is not None else [{"title": "SAPS Sandton"}]
        self.aborted = False
        self.start_calls: List[Dict[str, Any]] = []

    def post(self, url, params=None, json=None, timeout=None):
        if url.endswith("/abort"):
            self.aborted = True
            return FakeResponse({"data": {"status": "ABORTING"}})
        self.start_calls.append({"url": url, "input": json})
        return FakeResponse({"data": {
            "id": "run123",
            "defaultDatasetId": "ds456",
            "status": self.statuses.pop(0),
        }})

    def get(self, url, params=None, timeout=None):
        if "/actor-runs/" in url:
            return FakeResponse({"data": {"status": self.statuses.pop(0)}})
        if "/datasets/" in url:
            return FakeResponse(self.items)
        raise AssertionError(f"unexpected GET {url}")


@pytest.fixture
def no_sleep(monkeypatch):
    monkeypatch.setattr(apify_mod.time, "sleep", lambda s: None)


def _client(api, monkeypatch, **kwargs) -> ApifyClient:
    monkeypatch.setattr(apify_mod, "requests", api)
    return ApifyClient(token="test-token", **kwargs)


def test_slow_run_polled_to_completion_returns_items(monkeypatch, no_sleep):
    api = FakeApifyAPI(statuses=["RUNNING", "RUNNING", "RUNNING", "SUCCEEDED"])
    client = _client(api, monkeypatch)

    items = client.run_actor_sync("compass/crawler-google-places", {"q": "x"})

    assert items == [{"title": "SAPS Sandton"}]
    assert not api.aborted
    # actor id reaches the API in tilde form
    assert "compass~crawler-google-places" in api.start_calls[0]["url"]


def test_failed_run_returns_none_never_raises(monkeypatch, no_sleep):
    api = FakeApifyAPI(statuses=["RUNNING", "FAILED"])
    client = _client(api, monkeypatch)

    assert client.run_actor_sync("some/actor") is None
    assert not api.aborted  # already dead — nothing to abort


def test_deadline_exceeded_aborts_the_run(monkeypatch, no_sleep):
    api = FakeApifyAPI(statuses=["RUNNING"] * 50)
    client = _client(api, monkeypatch, timeout=1)

    clock = iter(range(0, 100))
    monkeypatch.setattr(apify_mod.time, "monotonic", lambda: next(clock))

    assert client.run_actor_sync("some/actor") is None
    assert api.aborted  # the credit-saver: a hung run is not left billing


def test_no_token_is_an_honest_none(monkeypatch):
    monkeypatch.delenv("APIFY_TOKEN", raising=False)
    client = ApifyClient(token=None)
    assert client.available() is False
    assert client.run_actor_sync("some/actor") is None
