"""
Dwell over motion stills — how long a person has stayed in view.

The recorder sends stills only while there is motion, seconds apart, so classic
video tracking (ByteTrack et al.) doesn't apply — but dwell doesn't need it: a
person who STAYS produces a run of person detections at the same camera in
roughly the same part of the frame. Chain those (IoU overlap, bounded time gap)
into presence spans; a span's duration is the dwell.

Honest limits, by construction: a span breaks whenever the chain breaks, so
this UNDER-reports dwell rather than inventing it. It says "a person remained
in view for N minutes" — continuity in one camera view, never identity.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

MAX_GAP_SECONDS = 120       # chain breaks if no matching detection for this long
MIN_IOU = 0.2               # loose: people shift while loitering
DEFAULT_MIN_DWELL_MINUTES = 3.0


def _iou(a, b) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix = max(0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0, min(ay + ah, by + bh) - max(ay, by))
    inter = ix * iy
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


def person_spans(detections: List[Dict[str, Any]],
                 max_gap_seconds: float = MAX_GAP_SECONDS,
                 min_iou: float = MIN_IOU) -> List[Dict[str, Any]]:
    """Chain per-camera person detections into presence spans. Pure.

    `detections`: [{camera_id, ts (datetime), bbox [x,y,w,h]}] in any order.
    Returns [{camera_id, start, end, minutes, sightings}] sorted by duration.
    """
    by_cam: Dict[str, List[Dict[str, Any]]] = {}
    for d in detections:
        if d.get("bbox") and len(d["bbox"]) == 4 and d.get("ts") is not None:
            by_cam.setdefault(d["camera_id"], []).append(d)

    spans: List[Dict[str, Any]] = []
    gap = timedelta(seconds=max_gap_seconds)
    for cam, rows in by_cam.items():
        rows.sort(key=lambda r: r["ts"])
        spans.extend(_collect_spans(cam, rows, gap, min_iou))
    spans.sort(key=lambda s: -s["minutes"])
    return spans


def _collect_spans(cam, rows, gap, min_iou) -> List[Dict[str, Any]]:
    all_spans: List[Dict[str, Any]] = []
    active: List[Dict[str, Any]] = []
    for r in rows:
        matched = None
        for sp in active:
            if r["ts"] - sp["end"] <= gap and _iou(r["bbox"], sp["bbox"]) >= min_iou:
                matched = sp
                break
        if matched:
            matched["end"] = r["ts"]
            matched["bbox"] = r["bbox"]
            matched["n"] += 1
        else:
            sp = {"start": r["ts"], "end": r["ts"], "bbox": r["bbox"], "n": 1}
            active.append(sp)
            all_spans.append(sp)
        active = [s for s in active if r["ts"] - s["end"] <= gap]
    return [{
        "camera_id": cam,
        "start": s["start"].isoformat(),
        "end": s["end"].isoformat(),
        "minutes": round((s["end"] - s["start"]).total_seconds() / 60.0, 1),
        "sightings": s["n"],
    } for s in all_spans]


def detections_from_events(events, camera_ids=None) -> List[Dict[str, Any]]:
    """Pull person detections (with bboxes) out of stored camera events."""
    cams = set(camera_ids or [])
    out = []
    for e in events:
        if cams and e.camera_id not in cams:
            continue
        intel = ((getattr(e, "metadata", None) or {}).get("intel") or {})
        for d in intel.get("detections") or []:
            if d.get("class") == "person":
                out.append({"camera_id": e.camera_id, "ts": e.ts, "bbox": d.get("bbox")})
    return out


def evaluate_dwell(site, events,
                   min_dwell_minutes: float = DEFAULT_MIN_DWELL_MINUTES) -> Dict[str, Any]:
    """The watching-for dwell evaluator: fired if any person presence span at
    the site's cameras lasted >= min_dwell_minutes."""
    spans = person_spans(detections_from_events(events, site.camera_ids))
    long_spans = [s for s in spans if s["minutes"] >= min_dwell_minutes]
    if not long_spans:
        return {"evaluated": True, "fired": False}
    top = long_spans[0]
    return {"evaluated": True, "fired": True, "ts": top["end"],
            "camera_id": top["camera_id"],
            "note": f"a person remained in view ~{top['minutes']:g} min ({top['sightings']} sightings)"}
