"""
Tests for colour-aware plate-vehicle mismatch.

Colour is the reliable vehicle attribute, so the mismatch check must fire on a
colour change (registered black car, camera sees white) even when make/model
classification is unavailable.
"""

import numpy as np

from alibi.vehicles.mismatch import (
    compute_color_mismatch, check_mismatch, MismatchResult,
)
from alibi.vehicles.vehicle_attrs import VehicleAttributeExtractor


# ── compute_color_mismatch ────────────────────────────────────────────────
def test_distinct_colour_is_strong_mismatch():
    score, expl = compute_color_mismatch("blue", "red", 0.9)
    assert score > 0.5
    assert "blue" in expl and "red" in expl


def test_same_colour_no_mismatch():
    score, _ = compute_color_mismatch("blue", "blue", 0.9)
    assert score == 0.0


def test_unknown_colour_no_mismatch():
    assert compute_color_mismatch("", "red", 0.9)[0] == 0.0
    assert compute_color_mismatch("blue", "unknown", 0.9)[0] == 0.0


def test_neutral_pair_is_weaker():
    strong, _ = compute_color_mismatch("blue", "red", 1.0)
    weak, _ = compute_color_mismatch("silver", "gray", 1.0)
    assert weak < strong


# ── check_mismatch fires on colour even when make/model unknown ────────────
def test_colour_mismatch_fires_without_make_model():
    r = check_mismatch(
        plate_text="N123W",
        expected_make="unknown", expected_model="unknown",
        observed_make="unknown", observed_model="unknown",
        observed_make_confidence=0.0, observed_model_confidence=0.0,
        expected_color="black", observed_color="white",
        observed_color_confidence=0.8,
    )
    assert isinstance(r, MismatchResult)
    assert r.is_mismatch and r.mismatch_score >= 0.3
    assert r.expected_color == "black" and r.observed_color == "white"


def test_colour_match_no_alert():
    r = check_mismatch(
        plate_text="N123W",
        expected_make="unknown", expected_model="unknown",
        observed_make="unknown", observed_model="unknown",
        observed_make_confidence=0.0, observed_model_confidence=0.0,
        expected_color="black", observed_color="black",
        observed_color_confidence=0.8,
    )
    assert r is None


def test_low_colour_confidence_no_alert():
    r = check_mismatch(
        plate_text="N123W",
        expected_make="unknown", expected_model="unknown",
        observed_make="unknown", observed_model="unknown",
        observed_make_confidence=0.0, observed_model_confidence=0.0,
        expected_color="black", observed_color="white",
        observed_color_confidence=0.1,  # below color_min_confidence
    )
    assert r is None


# ── colour classifier on solid colours ────────────────────────────────────
def _solid(bgr):
    img = np.zeros((120, 160, 3), dtype=np.uint8)
    img[:] = bgr
    return img


def test_colour_classifier_reads_solid_colours():
    ex = VehicleAttributeExtractor()
    assert ex.extract_attributes(_solid((0, 0, 255))).color == "red"
    assert ex.extract_attributes(_solid((255, 0, 0))).color == "blue"
    # make/model remains an honest placeholder (no classifier wired yet)
    assert ex.extract_attributes(_solid((0, 0, 255))).make == "unknown"
