"""
Tests for the camera `area` field — the switch that turns place-context (§9) on.

`area` is what links a camera to its area background. It must survive the whole
round-trip (create -> store -> update -> read) or the context feature silently
does nothing.

Honest default: no area set -> no context. We never guess an area from the
free-text `location`.
"""

import pytest

from alibi.alibi_api import CameraCreateRequest, CameraUpdateRequest
from alibi.cameras.camera_store import Camera, CameraStore
from alibi.dataengine.context import resolve_area_for_camera


@pytest.fixture
def store(tmp_path):
    return CameraStore(storage_path=str(tmp_path / "cams.json"))


def _cam(**kw):
    base = dict(camera_id="cam_1", name="North Gate", source="rtsp://x",
                source_type="rtsp")
    base.update(kw)
    return Camera(**base)


class TestCameraAreaModel:

    def test_defaults_to_empty(self, store):
        store.add(_cam())
        assert store.get("cam_1").area == ""   # no guessing

    def test_round_trips_through_disk(self, tmp_path):
        path = str(tmp_path / "cams.json")
        CameraStore(storage_path=path).add(_cam(area="Sandton"))

        reloaded = CameraStore(storage_path=path)   # fresh load from disk
        assert reloaded.get("cam_1").area == "Sandton"

    def test_serialises_in_to_dict(self):
        assert _cam(area="Rosebank").to_dict()["area"] == "Rosebank"

    def test_update_sets_area(self, store):
        store.add(_cam())
        cam = store.update("cam_1", {"area": "Sandton"})
        assert cam.area == "Sandton"
        assert store.get("cam_1").area == "Sandton"


class TestCameraAreaApiModels:

    def test_create_request_carries_area(self):
        req = CameraCreateRequest(camera_id="c", name="C", area="Sandton")
        assert req.area == "Sandton"

    def test_create_request_area_is_optional(self):
        assert CameraCreateRequest(camera_id="c", name="C").area == ""

    def test_partial_update_sends_only_area(self):
        """The PUT handler drops Nones — an area-only edit must not clobber
        the camera's source/name."""
        req = CameraUpdateRequest(area="Sandton")
        sent = {k: v for k, v in req.model_dump().items() if v is not None}
        assert sent == {"area": "Sandton"}


class TestContextResolution:

    def test_unknown_camera_resolves_to_no_area(self):
        assert resolve_area_for_camera("does-not-exist") == ""
