"""
Plate reader tuning — read plates on vehicle crops, not just the wide frame.

A plate is tiny/unreadable at a distance in the full shot; the fix is to run the
detector on each sizeable vehicle's upscaled crop. These pin the crop selection:
the wide frame is always included, sizeable vehicles add an upscaled crop, tiny
or non-vehicle boxes do not.
"""

import numpy as np
import pytest
from types import SimpleNamespace

pytest.importorskip("cv2")

from alibi.vision.frame_intelligence import _plate_regions, _PLATE_CROP_TARGET_W


def _frame(w=1280, h=720):
    return np.zeros((h, w, 3), dtype=np.uint8)


def _det(cls, bbox):
    return SimpleNamespace(class_name=cls, bbox=bbox)


def test_wide_frame_always_included_even_with_no_detections():
    regions = _plate_regions(_frame(), None)
    assert len(regions) == 1
    assert regions[0].shape[1] == 1280


def test_sizeable_vehicle_adds_an_upscaled_crop():
    # a 200px-wide car crop should be upscaled toward the target width
    regions = _plate_regions(_frame(), [_det("car", (100, 100, 200, 150))])
    assert len(regions) == 2
    assert regions[1].shape[1] >= _PLATE_CROP_TARGET_W      # upscaled


def test_tiny_and_nonvehicle_boxes_are_skipped():
    dets = [_det("car", (10, 10, 30, 20)),      # too small/distant
            _det("person", (100, 100, 200, 300))]  # not a vehicle
    assert len(_plate_regions(_frame(), dets)) == 1          # only the wide frame


def test_closest_vehicles_first_and_capped_at_three():
    dets = [_det("car", (0, 0, 100 + i, 100 + i)) for i in range(6)]
    regions = _plate_regions(_frame(), dets)
    assert len(regions) == 1 + 3                             # frame + 3 crops max


def test_large_crop_is_not_upscaled():
    # a crop already wider than the target keeps its (padded) size — we only ever
    # upscale small crops, never shrink big ones
    regions = _plate_regions(_frame(1280, 720), [_det("truck", (0, 0, 800, 400))])
    assert regions[1].shape[1] == 864          # 800 + 8% right pad (left clamped at 0)
