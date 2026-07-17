"""
Phase 4 — turn an uploaded still into an incident (economically).

The recording PC uploads motion-triggered stills (a few seconds apart, only when
something is happening — never a steady stream of an empty scene). The cloud runs
vision on each, and when it sees something worth a reviewer's attention (a person,
a vehicle, a safety concern) it creates a CameraEvent that flows into the existing
incident pipeline — which the explainer, area context, and security brief already
narrate.

Cost control:
  * frames are MOTION-gated on the edge (idle scene => no frames => no AI), and
  * analysis is throttled per camera (`should_analyze`) so a burst of motion
    can't fire the vision model dozens of times a second.

Safety (same posture as the rest of Vantage):
  * event types are neutral ("person_detected", not "intruder"); severity is
    capped below the maximum — a frame is "worth a look", never an accusation.
  * The scene description is stored as EVIDENCE (metadata), not as a claim; the
    explainer/brief phrase everything through the non-accusatory validator.

`decide_event` (the mapping from a vision result to an optional event) is pure and
unit-tested. The cv2 decode + vision call + storage are thin wiring around it.
"""

import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from alibi.schemas import CameraEvent

FRAMES_DIR = Path("alibi/data/frames")
ANALYZE_MIN_GAP_SECONDS = 8          # at most one vision call per camera per this

_VEHICLE_WORDS = ("car", "truck", "motorcycle", "bike", "bakkie", "van", "taxi", "bus")
_last_analyzed: Dict[str, float] = {}

# What each camera last saw, so we can tell PRESENCE from CHANGE.
_last_seen: Dict[str, tuple] = {}


def is_new_activity(camera_id: str, person_count: int, vehicle_count: int,
                    flagged: bool = False) -> bool:
    """True if this frame shows MORE than the camera's last frame did.

    Security cares about change, not presence. A car parked on the driveway is
    detected — correctly — in every single frame, so alerting on presence means
    'vehicle detected' every few seconds, all night, forever. Real-world proof:
    a white SUV parked in view raised an event on every frame it appeared in.

    So an event is only worth raising when the count goes UP (someone arrived, a
    second car pulled in). A scene that stays the same is furniture. Anything
    flagged (hotlist/watchlist) always passes — that's never furniture.

    Returns True and records the new baseline. Pure enough to test: state is a
    module dict keyed by camera, reset via `reset_activity_baseline`.
    """
    key = (int(person_count or 0), int(vehicle_count or 0))
    prev = _last_seen.get(camera_id)
    _last_seen[camera_id] = key
    if flagged:
        return True
    if prev is None:
        return key != (0, 0)          # first sighting is news, an empty scene isn't
    return key[0] > prev[0] or key[1] > prev[1]


def reset_activity_baseline(camera_id: Optional[str] = None) -> None:
    """Forget what a camera last saw (or all cameras)."""
    if camera_id is None:
        _last_seen.clear()
    else:
        _last_seen.pop(camera_id, None)


def should_analyze(camera_id: str, now: float, min_gap: float = ANALYZE_MIN_GAP_SECONDS) -> bool:
    """Throttle: True at most once per `min_gap` seconds per camera."""
    last = _last_analyzed.get(camera_id)
    if last is not None and (now - last) < min_gap:
        return False
    _last_analyzed[camera_id] = now
    return True


def decide_event(
    analysis: Dict[str, Any],
    camera_id: str,
    now: datetime,
    frame_id: str,
    intel: Optional[Dict[str, Any]] = None,
) -> Optional[CameraEvent]:
    """Map a frame's findings to a CameraEvent, or None if nothing merits a
    reviewer's attention. Pure + non-accusatory.

    `analysis` is the VLM scene result (description, objects, safety). `intel` is
    the optional structured-CV result from `frame_intelligence.analyze_and_record`
    (real person/vehicle counts, plate reads, watchlist/hotlist hits). When intel
    is present it is the RELIABLE signal — real detections drive the event and the
    VLM description becomes narration; a hotlist plate or watchlist face raises the
    event even if the VLM missed it."""
    intel = intel or {}
    objs = [str(o).lower() for o in (analysis.get("detected_objects") or [])]
    desc = str(analysis.get("description") or "")
    low = desc.lower()

    # When the detector ran, it IS the answer. Do not also substring-match the
    # VLM's prose: "No people are visible in this nighttime frame" contains the
    # word "people", so the naive match read a flat denial as a sighting and
    # stamped person_detected on an empty garden — every single frame.
    # The text match survives only as a fallback for when there is no detector.
    person_count = int(intel.get("person_count") or 0)
    vehicle_count = int(intel.get("vehicle_count") or 0)
    if intel:
        has_person = person_count > 0
        has_vehicle = vehicle_count > 0
    else:
        has_person = "person" in objs or "people" in low or "person" in low
        has_vehicle = (any(v in objs for v in _VEHICLE_WORDS)
                       or any(v in low for v in _VEHICLE_WORDS))
    safety = bool(analysis.get("safety_concern"))
    hotlist_hit = bool(intel.get("hotlist_hit"))
    watchlist_hit = bool(intel.get("watchlist_hit"))

    # Presence isn't news — MORE THAN NORMAL is. Each camera learns what it always
    # shows (a parked SUV, a shrub the detector calls a car) and stays quiet about
    # it; a person where there is normally none still raises. Comparing against a
    # learned median also survives detection flicker (1 -> 0 -> 1), which defeated
    # the older "changed since the last frame" rule.
    #
    # This runs BEFORE the "nothing to flag" return on purpose: the baseline must
    # observe EVERY analysed frame, empty ones included. Learning only from frames
    # that already had a detection is a biased sample — a camera could never learn
    # that it normally shows nothing, and a mostly-empty view learned from just a
    # handful of its own false positives.
    baseline_reason = None
    is_news = True
    flagged = bool(hotlist_hit or watchlist_hit or safety)
    if intel:
        composition = {"person": person_count, "vehicle": vehicle_count}
        try:
            from alibi.cameras.scene_baseline import get_scene_baseline
            bl = get_scene_baseline()
            # Judge against what we knew BEFORE this frame, then let it teach us.
            is_news, baseline_reason = bl.newsworthy(camera_id, composition, flagged=flagged)
            bl.observe(camera_id, composition)
        except Exception as e:                     # never let the baseline break ingest
            print(f"[frame-ai] scene baseline unavailable: {e}")
            is_news = is_new_activity(camera_id, person_count, vehicle_count, flagged=flagged)

    if not (has_person or has_vehicle or safety or hotlist_hit or watchlist_hit):
        return None                                  # honest: nothing to flag

    if intel and not is_news:
        return None

    if has_person:
        event_type, severity = "person_detected", 3
    elif has_vehicle:
        event_type, severity = "vehicle_detected", 2
    else:
        event_type, severity = "activity_detected", 2
    if safety:
        severity = min(severity + 1, 4)              # worth a closer look; never the max
    # A hotlist plate or watchlist face is the strongest "worth a look" signal —
    # bump to the review ceiling (still capped below max; never an accusation).
    if hotlist_hit or watchlist_hit:
        severity = 4

    conf = analysis.get("confidence", 0.7)
    try:
        conf = max(0.0, min(float(conf), 1.0))
    except (TypeError, ValueError):
        conf = 0.7

    metadata: Dict[str, Any] = {
        "source": "frame_ai",
        "description": desc,
        "detected_objects": objs,
        "safety_concern": safety,
    }
    # Fold in the structured evidence when we have it.
    if intel:
        metadata["intel"] = {
            "person_count": person_count,
            "vehicle_count": vehicle_count,
            "plates": intel.get("plates") or [],
            "faces": intel.get("faces") or [],
            "hotlist_hit": hotlist_hit,
            "hotlist_reason": intel.get("hotlist_reason"),
            "watchlist_hit": watchlist_hit,
            "watchlist_label": intel.get("watchlist_label"),
            "cross_camera_alerts": intel.get("cross_camera_alerts") or [],
            "detections": intel.get("detections") or [],
        }
        # The VLM's structured vehicle attributes (colour/make/model/body, each
        # honestly absent when unreadable) — a VLM opinion about an image, kept
        # as evidence, never a registry fact.
        if analysis.get("vehicles"):
            metadata["intel"]["vehicle_attrs"] = analysis["vehicles"]
        # Why this frame was worth raising when the camera's normal scene isn't —
        # the explainer and the brief can quote it verbatim.
        if baseline_reason:
            metadata["intel"]["why_raised"] = baseline_reason

    return CameraEvent(
        event_id=f"frm_{frame_id}",
        camera_id=camera_id,
        ts=now,
        zone_id="frame",
        event_type=event_type,
        confidence=conf,
        severity=severity,
        snapshot_url=f"/api/cameras/frames/{frame_id}.jpg",
        metadata=metadata,
    )


_VEHICLE_DET_CLASSES = {"car", "truck", "bus", "motorcycle"}


def record_vehicle_sightings(intel, vehicles, camera_id: str, now: datetime,
                             frame_id: str, sightings_store=None) -> int:
    """Persist a VehicleSighting per DETECTED vehicle in an analysed frame, so
    the vehicles surface (Overview strip, vehicle search) has real rows with the
    evidence frame + the vehicle's own bbox.

    Attributes come from the VLM's structured answer and are attached ONLY when
    the pairing is unambiguous — exactly one vehicle detected and one described.
    With several vehicles in frame we cannot know which description belongs to
    which bbox, and guessing would stamp one car's attributes on another — so
    those rows stay "unknown" (honest) with the raw VLM list kept on the event.
    Returns how many sightings were written; never raises.
    """
    import uuid as _uuid
    dets = [d for d in ((intel or {}).get("detections") or [])
            if d.get("class") in _VEHICLE_DET_CLASSES]
    if not dets:
        return 0
    vehicles = vehicles or []
    attach = vehicles[0] if (len(dets) == 1 and len(vehicles) == 1) else None
    try:
        from alibi.vehicles.sightings_store import VehicleSighting, VehicleSightingsStore
        if sightings_store is None:
            sightings_store = VehicleSightingsStore()
    except Exception as e:  # pragma: no cover
        print(f"[frame-ai] vehicle sightings store unavailable: {e}")
        return 0

    written = 0
    for d in dets:
        try:
            md = {"frame_id": frame_id, "source": "frame_ai", "class": d.get("class")}
            if attach:
                md["body"] = attach.get("body")
                md["attr_confidence"] = attach.get("confidence")
                md["attr_source"] = "vlm"
            sightings_store.add_sighting(VehicleSighting(
                sighting_id=str(_uuid.uuid4()),
                camera_id=camera_id,
                ts=now.isoformat(),
                bbox=tuple(int(v) for v in d.get("bbox") or (0, 0, 0, 0)),
                color=(attach.get("colour") if attach else None) or "unknown",
                make=(attach.get("make") if attach else None) or "unknown",
                model=(attach.get("model") if attach else None) or "unknown",
                confidence=float(d.get("confidence") or 0.0),
                snapshot_url=f"/api/cameras/frames/{frame_id}.jpg",
                metadata=md,
            ))
            written += 1
        except Exception as e:  # pragma: no cover
            print(f"[frame-ai] vehicle-sighting write failed: {e}")
    return written


# The Overview asks for a vehicle's colour per tile; decoding the same evidence
# frame on every 15s poll would be wasteful, so results (including "couldn't
# tell") are cached per (frame, bbox).
_colour_cache: Dict[tuple, Optional[str]] = {}
_COLOUR_CACHE_MAX = 4096
_colour_classifier = None

# Below this fraction of body pixels we don't claim a colour at all — an unsure
# colour in front of a client is worse than none.
_COLOUR_MIN_CONFIDENCE = 0.3


def vehicle_colour(frame_id: str, bbox) -> Optional[str]:
    """HSV colour of a vehicle crop from a stored evidence frame — deterministic,
    read from the actual pixels (never guessed), or None when it can't tell.
    Used as the fallback when an event predates (or didn't earn) VLM attributes."""
    global _colour_classifier
    try:
        key = (frame_id, tuple(int(v) for v in bbox))
    except (TypeError, ValueError):
        return None
    if key in _colour_cache:
        return _colour_cache[key]
    colour = None
    try:
        data = get_frame(frame_id)
        frame = _decode(data) if data else None
        if frame is not None:
            x, y, w, h = key[1]
            crop = frame[max(0, y):y + h, max(0, x):x + w]
            if crop.size:
                if _colour_classifier is None:
                    from alibi.vehicles.vehicle_attrs import VehicleAttributeClassifier
                    _colour_classifier = VehicleAttributeClassifier()
                c, conf = _colour_classifier._classify_color(crop)
                if c and c != "unknown" and conf >= _COLOUR_MIN_CONFIDENCE:
                    colour = c
    except Exception as e:
        print(f"[frame-ai] colour lookup failed: {e}")
    if len(_colour_cache) >= _COLOUR_CACHE_MAX:
        _colour_cache.clear()
    _colour_cache[key] = colour
    return colour


# --- frame storage (evidence) --------------------------------------------- #

def _safe_id(frame_id: str) -> str:
    return "".join(c for c in (frame_id or "") if c.isalnum() or c in "-_")[:80]


def store_frame(data: bytes) -> str:
    """Persist a frame as evidence; returns its id (used in the snapshot URL)."""
    FRAMES_DIR.mkdir(parents=True, exist_ok=True)
    frame_id = uuid.uuid4().hex[:16]
    (FRAMES_DIR / f"{frame_id}.jpg").write_bytes(data)
    return frame_id


def get_frame(frame_id: str) -> Optional[bytes]:
    try:
        return (FRAMES_DIR / f"{_safe_id(frame_id)}.jpg").read_bytes()
    except OSError:
        return None


def _decode(data: bytes):
    """JPEG bytes -> BGR frame (cv2/numpy). Kept out of decide_event so that
    stays pure and dependency-free for tests."""
    import cv2
    import numpy as np
    return cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)


# Public alias — the endpoint decodes once and shares the frame with both the VLM
# and the structured CV stack (avoids decoding the same JPEG twice).
def decode(data: bytes):
    return _decode(data)


def analyze_frame(frame, analyzer=None, want_vehicle_attrs: bool = False) -> Optional[Dict[str, Any]]:
    """Run the VLM on an already-decoded BGR frame -> SceneAnalyzer result dict
    (or None on failure). `analyzer` is injectable for tests.

    `want_vehicle_attrs` (set when the detector already found a vehicle) asks the
    SAME call for structured vehicle attributes — colour/make/model/body, each
    honestly absent when the model can't read it from the image."""
    if frame is None:
        return None
    if analyzer is None:
        from alibi.vision.scene_analyzer import SceneAnalyzer
        analyzer = SceneAnalyzer(mode="auto")
    try:
        prompt = "describe_scene_vehicles" if want_vehicle_attrs else "describe_scene"
        return analyzer.analyze_frame(frame, prompt)
    except Exception as e:
        print(f"[frame-ai] analysis failed: {e}")
        return None


def analyze_bytes(data: bytes, analyzer=None) -> Optional[Dict[str, Any]]:
    """Run vision on JPEG bytes -> the SceneAnalyzer result dict (or None on a
    decode/vision failure). `analyzer` is injectable for tests."""
    return analyze_frame(_decode(data), analyzer=analyzer)
