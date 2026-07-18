"""
Shared structured-CV intelligence for one frame.

This is the SAME detection / plate / face / vehicle-ReID stack the phone-camera
endpoint (`/camera/analyze-secure`) runs, factored out so the **house-camera
recorder path** (`/cameras/bridge/frame`) gets identical treatment — and, crucially,
writes the SAME sighting stores the pattern / history / co-occurrence engine reads.
Before this, those stores were only ever written by the phone endpoint, so on the
real (camera-on-a-house) architecture the pattern surfaces were structurally empty.

Design:
  * Reuses the phone stack's lazily-built singletons (via `get_security_components`)
    so the CV models load **once** in RAM — important on the small cloud box.
  * Event-gated by the caller: this only runs on motion-triggered, throttled
    frames, so the deep work stays economical (the locked architecture).
  * Every component degrades independently: a missing model backend (e.g. no
    `insightface` for faces) disables just that component and is caught — it never
    breaks the frame or the incident.
  * Safety posture unchanged: this RECORDS sightings and surfaces hotlist/watchlist
    hits as "worth a look". It never accuses; the incident layer phrases everything
    through the non-accusatory validator.

`analyze_and_record` returns a plain dict of structured findings that the frame
endpoint folds into the incident (real person/vehicle counts, plate reads,
watchlist/hotlist hits, cross-camera links) instead of substring-matching a VLM's
free text.
"""

import os
import threading
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

_VEHICLE_CLASSES = {"car", "truck", "bus", "motorcycle"}

# Minimum detection confidence we will act on.
#
# The detector returns everything it half-suspects, down to ~0.25. On a real
# night-time garden that flood looked like: cat 69, car 63, pottedplant 41,
# train 9, aeroplane 4, bear 1, broccoli 2 — median confidence 0.304, with the
# "person" detections that raised alerts scoring 0.273. Every frame became
# "person_detected", the owner would have been alerted all night about shrubs,
# and each false positive also bought a paid vision call.
#
# Genuine subjects score high (a real person in a clear frame: 0.94). 0.6 keeps
# those and drops ~94% of that noise. Tunable for a site that needs to reach
# further into the dark, at the cost of more false alarms.
_MIN_DETECTION_CONFIDENCE = float(os.environ.get("VANTAGE_MIN_DETECTION_CONF", "0.6"))

# Serialise the one-time model load: the first frame(s) trigger a ~30s build of
# the detection/face/ReID models. Without this, two cameras' first frames could
# both start building concurrently (double memory spike, wasted work).
_init_lock = threading.Lock()


def _mce():
    """The phone stack module, with its CV singletons initialised (models load
    once, under a lock). Imported lazily so this module stays cheap to import."""
    import alibi.mobile_camera_enhanced as mce
    with _init_lock:
        mce.get_security_components()
    return mce


def confident_detections(detections, min_conf: float = None) -> List[Any]:
    """Drop detections we shouldn't act on. Pure, so the threshold is testable."""
    floor = _MIN_DETECTION_CONFIDENCE if min_conf is None else min_conf
    out = []
    for d in detections or []:
        try:
            if float(getattr(d, "confidence", 0)) >= floor:
                out.append(d)
        except (TypeError, ValueError):
            continue
    return out


def _run_detection(mce, frame) -> List[Any]:
    try:
        det = mce._gatekeeper.process_frame(frame, zones_config=None)
        # Filter at source: everything downstream (counts, the incident decision,
        # the paid VLM gate, vehicle ReID crops) should only ever see detections
        # we actually believe.
        return confident_detections(det.get("detections", []))
    except Exception as e:  # pragma: no cover - depends on model backend
        print(f"[frame-intel] detection failed: {e}")
        return []


def _run_plates(mce, frame, camera_id: str, ts: datetime, out: Dict[str, Any]) -> None:
    """Detect + OCR plates; write a VehicleSighting, check the hotlist, and record
    a cross-camera + impossible-travel sighting. Mirrors the phone endpoint."""
    from alibi.plates.normalize import normalize_plate, format_plate_display
    from alibi.vehicles.sightings_store import VehicleSighting
    try:
        raw_plates = mce._plate_detector.detect(frame)
    except Exception as e:  # pragma: no cover
        print(f"[frame-intel] plate detect failed: {e}")
        return
    for plate in raw_plates or []:
        try:
            text, ocr_conf = mce._plate_ocr.read_plate(plate.plate_image)
        except Exception:
            continue
        if not text or ocr_conf < 0.5:
            continue
        normalized = normalize_plate(text)
        display_text = format_plate_display(normalized) if normalized else text
        plate_key = normalized or text
        is_hotlist = mce._hotlist_store.is_on_hotlist(normalized) if normalized else False
        hl_reason = None
        if is_hotlist:
            entry = mce._hotlist_store.get_by_plate(normalized)
            hl_reason = entry.reason if entry else "unknown"
            out["hotlist_hit"] = True
            out["hotlist_reason"] = hl_reason

        # Decode the plate's REGISTRATION region — where the vehicle is
        # registered (province/town), never where a person is "from". A
        # deterministic, free signal; out-of-province plates are worth a look.
        region = None
        try:
            from alibi.vehicles.plate_region import registration_note
            region = registration_note(plate_key)
        except Exception:
            region = None

        out["plates"].append({
            "text": plate_key, "display": display_text,
            "confidence": round(min(plate.confidence, ocr_conf), 2),
            "hotlist_match": is_hotlist, "hotlist_reason": hl_reason,
            "region": region,
        })

        try:
            plate_meta = {"plate_text": plate_key, "ocr_confidence": ocr_conf}
            if region:
                plate_meta["reg_province"] = region["province"]
                plate_meta["reg_town"] = region["town"]
                plate_meta["reg_out_of_area"] = region["out_of_area"]
            mce._sightings_store.add_sighting(VehicleSighting(
                sighting_id=str(uuid.uuid4()), camera_id=camera_id, ts=ts.isoformat(),
                bbox=plate.bbox, color="unknown", make="unknown", model="unknown",
                confidence=round(min(plate.confidence, ocr_conf), 2),
                metadata=plate_meta,
            ))
        except Exception as e:  # pragma: no cover
            print(f"[frame-intel] vehicle-sighting write failed: {e}")

        try:
            for ca in mce._cross_camera_tracker.record_sighting(
                camera_id=camera_id, entity_type="plate", entity_id=plate_key,
                timestamp=ts.isoformat(), metadata={"confidence": ocr_conf},
            ) or []:
                out["cross_camera_alerts"].append(
                    {"type": ca.alert_type, "message": ca.message, "cameras": ca.cameras})
                out["hotlist_hit"] = True
                out["hotlist_reason"] = ca.message
        except Exception:
            pass

        try:
            travel = mce._travel_detector.check(plate_key, camera_id, ts.isoformat())
            if travel:
                out["cross_camera_alerts"].append(
                    {"type": "impossible_travel", "message": travel.message,
                     "cameras": [travel.camera_a, camera_id]})
                out["hotlist_hit"] = True
                out["hotlist_reason"] = travel.message
        except Exception:
            pass


def face_within_person(face_bbox, person_boxes, pad: float = 0.35) -> bool:
    """A REAL face lies inside (or at the head of) a detected person. The face
    detector alone fires on texture — verified live: a tree and stone paving
    were both recorded as faces in frames where the person detector (correctly)
    found nobody. So a face candidate only counts when its centre falls inside
    a person bbox (padded, since SCRFD can slightly overshoot a head). Pure,
    so the gate is testable."""
    if not person_boxes:
        return False
    fx, fy, fw, fh = face_bbox
    cx, cy = fx + fw / 2.0, fy + fh / 2.0
    for (px, py, pw, ph) in person_boxes:
        dx, dy = pw * pad, ph * pad
        if (px - dx) <= cx <= (px + pw + dx) and (py - dy) <= cy <= (py + ph + dy):
            return True
    return False


def _run_faces(mce, frame, camera_id: str, ts: datetime, out: Dict[str, Any],
               frame_id: Optional[str] = None, person_boxes=None) -> None:
    """Detect faces; match against the watchlist; write a FaceSighting and a
    cross-camera appearance link. Degrades to nothing if the face backend is
    unavailable. Mirrors the phone endpoint.

    Gated on the person detector: no person in the frame -> no faces recorded,
    and a face candidate must sit inside a person bbox (see face_within_person).
    """
    from alibi.watchlist.face_sighting_store import FaceSighting, get_face_sighting_store
    if not person_boxes:
        return
    try:
        scored = mce._face_detector.detect_scored(frame)
    except AttributeError:                      # older detector: no scores
        scored = [(b, 0.0) for b in mce._face_detector.detect(frame)]
    except Exception as e:  # pragma: no cover
        print(f"[frame-intel] face detect failed: {e}")
        return
    faces = [(b, s) for b, s in scored if face_within_person(b, person_boxes)]
    if not faces:
        return
    try:
        watchlist_embeddings = mce._watchlist_store.get_all_embeddings()
        watchlist_labels = {e.person_id: e.label for e in mce._watchlist_store.load_all()}
    except Exception:
        watchlist_embeddings, watchlist_labels = [], {}

    for bbox, det_score in faces:
        try:
            face_crop = mce._face_detector.extract_face(frame, bbox)
            embedding = mce._face_embedder.generate_embedding(face_crop)
        except Exception:
            continue
        is_match, best_score, top = False, 0.0, []
        if watchlist_embeddings is not None and len(watchlist_embeddings):
            try:
                is_match, top, best_score = mce._face_matcher.match(
                    embedding, watchlist_embeddings, watchlist_labels)
            except Exception:
                is_match, top, best_score = False, [], 0.0
        if is_match and top:
            out["watchlist_hit"] = True
            out["watchlist_label"] = top[0].label
            out["faces"].append({"watchlist_match": True, "label": top[0].label,
                                 "score": round(float(best_score), 3)})
            try:
                mce._cross_camera_tracker.record_sighting(
                    camera_id=camera_id, entity_type="face", entity_id=top[0].person_id,
                    timestamp=ts.isoformat(),
                    metadata={"score": best_score, "label": out["watchlist_label"]})
            except Exception:
                pass
        else:
            out["faces"].append({"watchlist_match": False})

        try:
            # Point the sighting at the evidence frame it came from, so a reviewer
            # can actually SEE the face behind a "seen here before" result rather
            # than an anonymous row. bbox locates the face within that frame.
            get_face_sighting_store().add_sighting(FaceSighting(
                sighting_id=str(uuid.uuid4()), camera_id=camera_id, ts=ts.isoformat(),
                embedding=embedding.tolist() if hasattr(embedding, "tolist") else list(embedding),
                bbox=tuple(bbox), confidence=best_score if is_match else 0.0,
                matched_person_id=top[0].person_id if (is_match and top) else None,
                match_score=best_score if is_match else None,
                image_path=(f"/api/cameras/frames/{frame_id}.jpg" if frame_id else None),
                metadata={**({"frame_id": frame_id} if frame_id else {}),
                          "det_score": round(float(det_score), 3)},
            ))
            if not is_match and embedding is not None:
                mce._cross_camera_tracker.record_appearance_sighting(
                    camera_id=camera_id, entity_type="unknown_face", embedding=embedding,
                    timestamp=ts.isoformat(), match_threshold=0.85, id_prefix="unknown_face")
        except Exception as e:  # pragma: no cover
            print(f"[frame-intel] face-sighting write failed: {e}")


def _run_vehicle_reid(mce, frame, detections, camera_id: str, ts: datetime, out: Dict[str, Any]) -> None:
    """Link the SAME vehicle across cameras by appearance (ReID embedding), even
    with no readable plate. Uses the detector's vehicle crops. Mirrors the phone
    endpoint."""
    embedder = getattr(mce, "_vehicle_embedder", None)
    if embedder is None or not getattr(embedder, "available", False):
        return
    for d in detections:
        if d.class_name not in _VEHICLE_CLASSES:
            continue
        try:
            x, y, w, h = d.bbox
            x, y = max(0, int(x)), max(0, int(y))
            crop = frame[y:y + int(h), x:x + int(w)]
            if crop.size == 0:
                continue
            emb = embedder.embed(crop)
            if emb is None:
                continue
            _eid, alerts = mce._cross_camera_tracker.record_appearance_sighting(
                camera_id=camera_id, entity_type="vehicle", embedding=emb,
                timestamp=ts.isoformat(),
                metadata={"class": d.class_name, "det_confidence": round(float(d.confidence), 3)},
                match_threshold=0.6, id_prefix="vehicle")
            for ca in alerts or []:
                out["cross_camera_alerts"].append(
                    {"type": ca.alert_type, "message": ca.message, "cameras": ca.cameras})
        except Exception as e:  # pragma: no cover
            print(f"[frame-intel] vehicle-reid failed: {e}")


def analyze_and_record(frame, camera_id: str, ts: datetime,
                       frame_id: Optional[str] = None) -> Dict[str, Any]:
    """Run the structured CV stack on one BGR frame, WRITE the sighting stores,
    and return the structured findings. Each stage is independently guarded.

    Returns a dict:
      person_count, vehicle_count : int
      plates  : list of {text, display, confidence, hotlist_match, hotlist_reason}
      faces   : list of {watchlist_match, [label, score]}
      hotlist_hit / hotlist_reason
      watchlist_hit / watchlist_label
      cross_camera_alerts : list of {type, message, cameras}
      detections : list of {class, confidence, bbox}
    """
    out: Dict[str, Any] = {
        "person_count": 0, "vehicle_count": 0,
        "plates": [], "faces": [], "cross_camera_alerts": [], "detections": [],
        "hotlist_hit": False, "hotlist_reason": None,
        "watchlist_hit": False, "watchlist_label": None,
    }
    if frame is None:
        return out
    try:
        mce = _mce()
    except Exception as e:  # pragma: no cover - only if the phone stack import fails
        print(f"[frame-intel] components unavailable: {e}")
        return out

    detections = _run_detection(mce, frame)
    out["detections"] = [
        {"class": d.class_name, "confidence": round(float(d.confidence), 3),
         "bbox": [int(v) for v in d.bbox]} for d in detections
    ]
    out["person_count"] = sum(1 for d in detections if d.class_name == "person")
    out["vehicle_count"] = sum(1 for d in detections if d.class_name in _VEHICLE_CLASSES)

    _run_plates(mce, frame, camera_id, ts, out)
    person_boxes = [tuple(d.bbox) for d in detections if d.class_name == "person"]
    _run_faces(mce, frame, camera_id, ts, out, frame_id=frame_id, person_boxes=person_boxes)
    _run_vehicle_reid(mce, frame, detections, camera_id, ts, out)
    return out
