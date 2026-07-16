"""
The detector returns everything it half-suspects (down to ~0.25). Against a real
night-time garden that produced: cat 69, car 63, pottedplant 41, train 9,
aeroplane 4, bear 1, broccoli 2 — median confidence 0.304 — and the "person"
detections that raised alerts scored 0.273. Every frame became person_detected,
the owner would have been woken by shrubs, and each false positive also bought a
paid vision call.

These pin the floor that stops that, using the confidences actually observed.
"""

from alibi.vision.frame_intelligence import confident_detections, _MIN_DETECTION_CONFIDENCE


class D:
    def __init__(self, confidence, class_name):
        self.confidence = confidence
        self.class_name = class_name


# Real detections observed on Paul's camera at night (all noise).
NIGHT_GARDEN_NOISE = [
    D(0.273, "person"), D(0.596, "cat"), D(0.572, "car"), D(0.346, "pottedplant"),
    D(0.277, "bear"), D(0.283, "traffic light"), D(0.271, "vase"), D(0.269, "car"),
]
# Real detections observed on a clear frame containing actual people and a bus.
REAL_SUBJECTS = [D(0.94, "person"), D(0.925, "person"), D(0.905, "bus"), D(0.913, "person")]


def test_night_garden_noise_is_entirely_rejected():
    assert confident_detections(NIGHT_GARDEN_NOISE) == []


def test_the_false_person_that_caused_the_alerts_is_dropped():
    # 0.273 "person" in a dark garden is what raised person_detected all night.
    assert confident_detections([D(0.273, "person")]) == []


def test_real_subjects_all_survive():
    kept = confident_detections(REAL_SUBJECTS)
    assert len(kept) == len(REAL_SUBJECTS)


def test_floor_is_sane():
    # High enough to kill ~0.3 noise, low enough to keep genuine subjects.
    assert 0.45 <= _MIN_DETECTION_CONFIDENCE <= 0.75


def test_threshold_is_overridable_for_a_site_that_needs_reach():
    assert len(confident_detections(NIGHT_GARDEN_NOISE, min_conf=0.25)) == len(NIGHT_GARDEN_NOISE)
    assert confident_detections(REAL_SUBJECTS, min_conf=0.99) == []


def test_boundary_is_inclusive():
    assert len(confident_detections([D(_MIN_DETECTION_CONFIDENCE, "person")])) == 1


def test_malformed_detections_do_not_crash():
    assert confident_detections([D("nonsense", "person"), D(None, "car")]) == []
    assert confident_detections([]) == []
    assert confident_detections(None) == []
