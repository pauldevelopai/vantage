"""
Observed actions around vehicles — "someone among the parked cars".

This is the honest version of "flag people who might be up to something": we do
NOT guess intent from how a person looks or walks. We report a concrete, visible
ACTION — a person lingering at, or moving between, parked vehicles (the thing a
guard actually watches for: someone trying car doors down the road).

It is built only from what the detector already gives us per motion still:
person boxes and vehicle boxes. A person is "at a vehicle" when their box falls
inside a vehicle's box grown by a halo (standing at the door, not merely in the
same wide frame). Chain those moments per camera (bounded time gap) into a span;
a span that lasts a while, or that touches SEVERAL distinct vehicles, is worth a
look. Under-reports by construction — the chain breaks whenever contact breaks,
so we never invent loitering that wasn't there.

Language stays situational: "a person was among the parked vehicles… near 3 of
them", never "a suspect", never "checking to steal". Describe, don't accuse.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict, List, Optional

VEHICLE_CLASSES = ("car", "truck", "bus", "motorcycle")
HALO_FRAC = 0.4              # grow each vehicle box by this fraction of its size
MAX_GAP_SECONDS = 120        # a person's "at the cars" chain breaks after this
MIN_DISTINCT_VEHICLES = 2    # near this many different cars = moving between them
MIN_DWELL_MINUTES = 1.5      # or lingering at the cars at least this long


def _inside_halo(person, vehicle, halo_frac: float = HALO_FRAC) -> bool:
    """True if the person box intersects the vehicle box grown by a halo — i.e.
    the person is standing AT the vehicle, not just elsewhere in the frame."""
    px, py, pw, ph = person
    vx, vy, vw, vh = vehicle
    mx, my = vw * halo_frac, vh * halo_frac
    gx0, gy0, gx1, gy1 = vx - mx, vy - my, vx + vw + mx, vy + vh + my
    ix = max(0, min(px + pw, gx1) - max(px, gx0))
    iy = max(0, min(py + ph, gy1) - max(py, gy0))
    return ix > 0 and iy > 0


def _vehicle_key(bbox) -> tuple:
    """A coarse identity for a parked vehicle box so re-detections of the SAME
    car (jittering a few px frame-to-frame) count once, not as many cars."""
    x, y, w, h = bbox
    return (round(x / 40.0), round(y / 40.0), round(w / 40.0), round(h / 40.0))


def vehicle_contact_spans(detections: List[Dict[str, Any]],
                          max_gap_seconds: float = MAX_GAP_SECONDS,
                          halo_frac: float = HALO_FRAC) -> List[Dict[str, Any]]:
    """Chain per-camera moments of "a person at the vehicles" into spans. Pure.

    `detections`: [{camera_id, ts (datetime), persons:[bbox], vehicles:[bbox]}]
    in any order — one row per motion still.
    Returns [{camera_id, start, end, minutes, sightings, vehicles_touched}]
    sorted by (vehicles_touched, minutes) descending.
    """
    by_cam: Dict[str, List[Dict[str, Any]]] = {}
    for d in detections:
        if d.get("ts") is None:
            continue
        contacts = []
        veh = [v for v in (d.get("vehicles") or []) if v and len(v) == 4]
        for p in (d.get("persons") or []):
            if not p or len(p) != 4:
                continue
            for v in veh:
                if _inside_halo(p, v, halo_frac):
                    contacts.append(_vehicle_key(v))
        if contacts:
            by_cam.setdefault(d["camera_id"], []).append(
                {"ts": d["ts"], "keys": set(contacts)})

    gap = timedelta(seconds=max_gap_seconds)
    spans: List[Dict[str, Any]] = []
    for cam, rows in by_cam.items():
        rows.sort(key=lambda r: r["ts"])
        cur: Optional[Dict[str, Any]] = None
        for r in rows:
            if cur is not None and r["ts"] - cur["end"] <= gap:
                cur["end"] = r["ts"]
                cur["n"] += 1
                cur["keys"] |= r["keys"]
            else:
                if cur is not None:
                    spans.append(cur)
                cur = {"camera_id": cam, "start": r["ts"], "end": r["ts"],
                       "n": 1, "keys": set(r["keys"])}
        if cur is not None:
            spans.append(cur)

    out = [{
        "camera_id": s["camera_id"],
        "start": s["start"].isoformat(),
        "end": s["end"].isoformat(),
        "minutes": round((s["end"] - s["start"]).total_seconds() / 60.0, 1),
        "sightings": s["n"],
        "vehicles_touched": len(s["keys"]),
    } for s in spans]
    out.sort(key=lambda s: (-s["vehicles_touched"], -s["minutes"]))
    return out


def detections_from_events(events, camera_ids=None) -> List[Dict[str, Any]]:
    """Pull per-still person + vehicle boxes out of stored camera events."""
    cams = set(camera_ids or [])
    out = []
    for e in events:
        if cams and e.camera_id not in cams:
            continue
        intel = ((getattr(e, "metadata", None) or {}).get("intel") or {})
        persons, vehicles = [], []
        for d in intel.get("detections") or []:
            bbox = d.get("bbox")
            if not bbox or len(bbox) != 4:
                continue
            if d.get("class") == "person":
                persons.append(bbox)
            elif d.get("class") in VEHICLE_CLASSES:
                vehicles.append(bbox)
        if persons and vehicles:
            out.append({"camera_id": e.camera_id, "ts": e.ts,
                        "persons": persons, "vehicles": vehicles})
    return out


def evaluate_at_vehicles(site, events,
                         min_distinct: int = MIN_DISTINCT_VEHICLES,
                         min_dwell_minutes: float = MIN_DWELL_MINUTES) -> Dict[str, Any]:
    """Fired when a person was among the parked vehicles at the site's cameras —
    either near several distinct vehicles, or lingering at them. Honest, factual,
    never accusatory. Returns the watching-for style {evaluated, fired, …}."""
    cam_ids = getattr(site, "camera_ids", None)
    spans = vehicle_contact_spans(detections_from_events(events, cam_ids))
    for s in spans:
        touched = s["vehicles_touched"]
        lingered = s["minutes"] >= min_dwell_minutes
        if touched >= min_distinct or lingered:
            if touched >= min_distinct and lingered:
                note = (f"a person moved between {touched} of the parked vehicles "
                        f"over ~{s['minutes']:g} min — worth a look")
            elif touched >= min_distinct:
                note = (f"a person was near {touched} different parked vehicles "
                        f"— worth a look")
            else:
                note = (f"a person lingered at a parked vehicle ~{s['minutes']:g} min "
                        f"— worth a look")
            return {"evaluated": True, "fired": True, "ts": s["end"],
                    "camera_id": s["camera_id"], "minutes": s["minutes"],
                    "vehicles_touched": touched, "note": note}
    return {"evaluated": True, "fired": False}
