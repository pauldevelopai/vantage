"""Plate matching: reject the date-overlay reads, tolerate OCR slips, never
merge genuinely different plates. These are the exact real-data cases that had
one car showing up as several 'vehicles' on the Overview."""

from alibi.vehicles.plate_match import (
    normalize_plate, is_plausible_plate, plates_match, resolve_label,
)


def test_normalize_strips_spaces_and_case():
    assert normalize_plate("csm4 0008") == "CSM40008"
    assert normalize_plate("  SKK4-0288 ") == "SKK40288"
    assert normalize_plate(None) == ""


def test_real_plates_are_plausible():
    assert is_plausible_plate("SKK4 0288")
    assert is_plausible_plate("CSM4 0008")


def test_date_overlay_read_is_rejected():
    # OCR read the burnt-in year off the timestamp overlay.
    assert not is_plausible_plate("2026QX")
    assert not is_plausible_plate("2025")
    assert not is_plausible_plate("07-17-17")


def test_ocr_slip_matches_same_plate():
    # 'GFM4 0008' is a two-letter misread of 'CSM4 0008' — same length, same car.
    assert plates_match("GFM4 0008", "CSM4 0008")
    assert plates_match("CSM4 0008", "CSM4 O008")  # zero/O confusion


def test_different_plates_do_not_match():
    assert not plates_match("SKK4 0288", "CSM4 0008")
    assert not plates_match("SKK4 0288", "2026QX")   # never match a bogus read


def test_resolve_inherits_named_label_through_a_slip():
    p2l = {"CSM4 0008": "Arnold's Haval", "SKK4 0288": "My Toyota"}
    assert resolve_label("GFM4 0008", p2l) == "Arnold's Haval"   # fuzzy
    assert resolve_label("SKK4 0288", p2l) == "My Toyota"        # exact
    assert resolve_label("2026QX", p2l) is None                  # bogus → no guess
    assert resolve_label(None, p2l) is None
