"""
Cameras added from a network scan all inherit the vendor name, so a two-camera
house ends up with two cameras both called "Dahua". On the dashboard camera wall
that is two identical tiles with no way to tell the driveway from the front gate.
Names that collide must be disambiguated; names that don't must be left alone.
"""

from unittest.mock import patch


class _Cam:
    def __init__(self, camera_id, name):
        self.camera_id = camera_id
        self.name = name


def _with(cams):
    store = type("S", (), {"list_all": lambda self: cams})()
    with patch("alibi.cameras.camera_store.get_camera_store", return_value=store):
        from alibi.alibi_api import _display_names
        return _display_names()


def test_colliding_names_are_disambiguated_by_ip_tail():
    out = _with([_Cam("dahua-192-168-3-91", "Dahua"), _Cam("dahua-192-168-3-92", "Dahua")])
    assert out["dahua-192-168-3-91"] == "Dahua ·91"
    assert out["dahua-192-168-3-92"] == "Dahua ·92"
    assert out["dahua-192-168-3-91"] != out["dahua-192-168-3-92"]   # the whole point


def test_unique_names_are_left_alone():
    out = _with([_Cam("dahua-192-168-3-91", "Front Gate"), _Cam("dahua-192-168-3-92", "Driveway")])
    assert out["dahua-192-168-3-91"] == "Front Gate"      # no noise added
    assert out["dahua-192-168-3-92"] == "Driveway"


def test_mixed_only_disambiguates_the_collision():
    out = _with([_Cam("dahua-192-168-3-91", "Dahua"), _Cam("dahua-192-168-3-92", "Dahua"),
                 _Cam("gate-1", "Front Gate")])
    assert out["gate-1"] == "Front Gate"
    assert out["dahua-192-168-3-91"] == "Dahua ·91"


def test_no_cameras_is_not_an_error():
    assert _with([]) == {}
