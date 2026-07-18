"""
Plate registration-region decode — pinned.

The security value is the honest, confident cases: local Western Cape vs clearly
out-of-province. Ambiguous plates must decode to unknown, never a guess; and the
language is always "registered in …", never "the person is from …".
"""

from alibi.vehicles.plate_region import decode_plate_region, registration_note


def test_western_cape_local():
    r = decode_plate_region("CA 123-456")
    assert r["province"] == "Western Cape"
    assert r["town"] == "Cape Town"
    assert r["confidence"] == "high"


def test_somerset_west_town_code():
    r = decode_plate_region("CEM 12345")
    assert r["province"] == "Western Cape"
    assert r["town"] == "Somerset West"


def test_gauteng_suffix_out_of_province():
    r = decode_plate_region("BX 12 ZR GP")
    assert r["province"] == "Gauteng"
    assert r["confidence"] == "high"


def test_kzn_prefix():
    assert decode_plate_region("ND 123-456")["province"] == "KwaZulu-Natal"


def test_unknown_plate_is_not_guessed():
    r = decode_plate_region("12345")          # no letters to place
    assert r["province"] is None
    assert r["confidence"] == "unknown"
    r2 = decode_plate_region("XY 999")        # nothing our rules cover
    assert r2["province"] is None


def test_note_flags_out_of_area_against_western_cape():
    note = registration_note("BX 12 ZR GP", site_province="Western Cape")
    assert note["out_of_area"] is True
    assert "out of province" in note["text"]
    assert "Registered in" in note["text"]     # never "from"


def test_note_local_plate_not_out_of_area():
    note = registration_note("CA 123-456", site_province="Western Cape")
    assert note["out_of_area"] is False
    assert "(local)" in note["text"]


def test_note_none_for_undecodable_plate():
    assert registration_note("12345") is None
