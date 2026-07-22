"""
Which cameras are actually being watched right now.

The Cameras page listed two cameras with no indication that neither had sent a
frame in two days — the recorder that reads them had been offline since the
20th, and nothing on screen said so. A camera list that looks identical whether
it is recording or dead is worse than no list: it answers a question it has not
actually checked.

Two different facts, deliberately kept apart:

  watching   something is alive and pointed at this camera right now — the
             recorder or handset that feeds it is checking in.
  last frame when a picture last arrived. On a still scene that can be a long
             time ago and nothing is wrong, because frames are only sent when
             something changes.

Conflating them is how you get a green light on a dead camera (heartbeat but no
pictures) or a red one on a working camera watching an empty driveway.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

# A feeder that has not checked in for this long is not watching any more.
# Generous: the phone heartbeats every 60s and the recorder polls for jobs, so
# a couple of missed check-ins is a slow network, not a dead camera.
WATCHING_TIMEOUT_MINUTES = 5

# How recently a picture must have arrived to call the view "live" rather than
# merely connected.
FRESH_FRAME_MINUTES = 10


def _parse(ts) -> Optional[datetime]:
    if not ts:
        return None
    if isinstance(ts, datetime):
        return ts
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "").strip())
    except (ValueError, TypeError):
        return None


def describe(feeder_last_seen, last_frame_ts, now: Optional[datetime] = None) -> dict:
    """What to say about one camera.

    `feeder_last_seen` is the recorder/handset check-in; `last_frame_ts` is the
    last picture. Returns {watching, state, label, detail} — `state` for a
    colour, `label` and `detail` for a person.
    """
    now = now or datetime.now()
    feeder = _parse(feeder_last_seen)
    frame = _parse(last_frame_ts)

    watching = bool(feeder and (now - feeder) <= timedelta(minutes=WATCHING_TIMEOUT_MINUTES))
    fresh = bool(frame and (now - frame) <= timedelta(minutes=FRESH_FRAME_MINUTES))

    if watching and fresh:
        return {"watching": True, "state": "live", "label": "Recording",
                "detail": f"last picture {_ago(now - frame)} ago"}
    if watching:
        return {"watching": True, "state": "quiet", "label": "Recording",
                "detail": ("nothing has moved" if frame is None
                           else f"quiet since {_ago(now - frame)} ago")}
    if frame is not None:
        return {"watching": False, "state": "stopped", "label": "Not recording",
                "detail": f"last picture {_ago(now - frame)} ago"}
    return {"watching": False, "state": "never", "label": "Not recording",
            "detail": "no pictures yet"}


def _ago(delta: timedelta) -> str:
    s = max(0, int(delta.total_seconds()))
    if s < 90:
        return f"{s}s"
    m = s // 60
    if m < 90:
        return f"{m} min"
    h = m // 60
    if h < 48:
        return f"{h}h"
    return f"{h // 24} days"
