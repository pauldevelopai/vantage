"""
Saying which cameras are actually being recorded. Pinned.

The Cameras page listed Driveway and Front Gate identically for two days after
the recorder that reads them went offline on 2026-07-20. Nothing on screen said
so. A list that looks the same whether a camera is recording or dead answers a
question it never checked.

The trap is conflating two different facts: something is watching (the recorder
or handset is checking in) versus a picture arrived recently. Frames are only
sent when something CHANGES, so a working camera on a still driveway is quiet,
not dead — and a feeder that heartbeats while its camera feed is broken is
connected, not recording.
"""

from datetime import datetime, timedelta

from alibi.cameras import liveness as lv


NOW = datetime(2026, 7, 22, 13, 30, 0)


def _ago(**kw):
    return NOW - timedelta(**kw)


def test_a_camera_being_watched_with_recent_pictures_is_live():
    d = lv.describe(_ago(seconds=30), _ago(seconds=20), now=NOW)
    assert d["watching"] is True
    assert d["state"] == "live"
    assert d["label"] == "Recording"


def test_a_still_scene_is_still_recording():
    """The one that matters most. Nothing has moved for an hour on a driveway
    that is being watched — that is a quiet camera, not a broken one."""
    d = lv.describe(_ago(seconds=20), _ago(hours=1), now=NOW)
    assert d["watching"] is True
    assert d["label"] == "Recording"
    assert d["state"] == "quiet"


def test_a_camera_nothing_is_watching_says_so_however_recent_the_last_picture():
    """The failure that hid for two days: pictures from Sunday, recorder dead
    since. The pictures do not make it a recording camera."""
    d = lv.describe(_ago(days=2), _ago(days=2), now=NOW)
    assert d["watching"] is False
    assert d["label"] == "Not recording"
    assert "2 days" in d["detail"]


def test_a_feeder_that_stopped_moments_ago_is_already_not_recording():
    d = lv.describe(_ago(minutes=lv.WATCHING_TIMEOUT_MINUTES + 1), _ago(minutes=6), now=NOW)
    assert d["watching"] is False


def test_a_brief_network_hiccup_does_not_read_as_dead():
    """A couple of missed check-ins is a slow line, not a stopped camera."""
    d = lv.describe(_ago(minutes=2), _ago(minutes=3), now=NOW)
    assert d["watching"] is True


def test_a_camera_that_has_never_sent_anything_is_honest_about_it():
    d = lv.describe(None, None, now=NOW)
    assert d["watching"] is False
    assert d["detail"] == "no pictures yet"

    d2 = lv.describe(_ago(seconds=10), None, now=NOW)
    assert d2["watching"] is True
    assert d2["detail"] == "nothing has moved"


def test_rubbish_timestamps_do_not_claim_a_camera_is_recording():
    """Failing towards "not recording" is the safe direction — claiming a dead
    camera is live is the error that costs someone something."""
    for bad in ("", "not a date", "2026-13-45T99:99:99", 12345):
        d = lv.describe(bad, bad, now=NOW)
        assert d["watching"] is False


def test_the_wording_is_readable():
    assert lv._ago(timedelta(seconds=45)) == "45s"
    assert lv._ago(timedelta(minutes=5)) == "5 min"
    assert lv._ago(timedelta(hours=3)) == "3h"
    assert lv._ago(timedelta(days=2)) == "2 days"
    assert lv._ago(timedelta(seconds=-5)) == "0s"
