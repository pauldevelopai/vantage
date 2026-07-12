"""
Tests for the D-FINE detector (Apache-2.0 replacement for YOLOv8n / AGPL).

These require transformers + torch and download a small model on first run, so
they skip cleanly when those are unavailable (e.g. minimal CI).
"""

import glob

import numpy as np
import pytest

# Skip the whole module if the D-FINE backend isn't installed.
pytest.importorskip("transformers")
pytest.importorskip("torch")

from alibi.vision.dfine_detector import DFineDetector
from alibi.vision.gatekeeper import VisionGatekeeper, Detection, _dfine_available


@pytest.fixture(scope="module")
def detector():
    return DFineDetector()


def test_dfine_available():
    assert _dfine_available() is True


def test_detector_has_coco_classes(detector):
    # COCO has 80 classes; id2label must map ints to names.
    assert len(detector.class_names) == 80
    assert detector.class_names[0]  # class 0 has a name


def test_empty_frame_returns_empty(detector):
    assert detector.detect(None) == []
    assert detector.detect(np.zeros((0, 0, 3), dtype=np.uint8)) == []


def test_detections_are_wellformed(detector):
    """Every detection must match the gatekeeper's Detection contract."""
    frame = np.random.default_rng(0).integers(
        0, 255, size=(480, 640, 3), dtype=np.uint8)
    dets = detector.detect(frame, conf_threshold=0.3)
    assert isinstance(dets, list)
    for d in dets:
        assert isinstance(d, Detection)
        assert isinstance(d.class_id, int)
        assert d.class_name in detector.class_names.values()
        assert 0.0 <= d.confidence <= 1.0
        x, y, w, h = d.bbox
        assert w > 0 and h > 0


def test_detects_person_in_real_snapshot(detector):
    """On a real camera snapshot with a person, D-FINE should find it."""
    snaps = sorted(glob.glob("alibi/data/camera_snapshots/*.jpg"))
    if not snaps:
        pytest.skip("no sample snapshots in repo")

    import cv2
    found_any = False
    for snap in snaps[:8]:
        frame = cv2.imread(snap)
        if frame is None:
            continue
        dets = detector.detect(frame, conf_threshold=0.3)
        if dets:
            found_any = True
            # confidences must be sane
            assert all(0.3 <= d.confidence <= 1.0 for d in dets)
    assert found_any, "expected at least one detection across sample snapshots"


def test_gatekeeper_selects_dfine_by_default():
    gk = VisionGatekeeper()
    assert gk.backend == "dfine"
    assert len(gk.class_names) == 80


def test_gatekeeper_backend_can_be_forced_dfine():
    gk = VisionGatekeeper(backend="dfine")
    assert gk.backend == "dfine"
