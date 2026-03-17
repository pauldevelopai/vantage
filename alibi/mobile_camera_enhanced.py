"""
Enhanced Mobile Camera with Security Threat Detection

NEW FEATURES:
- Real-time threat level assessment
- Visual threat warnings
- Red flag capability
- Integrated with tracking + incident manager
- Automatic flow to training data
"""

from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Body
from fastapi.responses import HTMLResponse
import cv2
import numpy as np
import base64
from datetime import datetime
import uuid

from dataclasses import asdict
from typing import Optional, List

from alibi.auth import User, get_current_user
from alibi.intelligence_store import IntelligenceStore, RedFlag
from alibi.vision.gatekeeper import VisionGatekeeper, GatekeeperPolicy
from alibi.vision.tracking import MultiObjectTracker
from alibi.rules.events import RuleEvaluator
from alibi.vision.simulate import IncidentManager
from alibi.vision.scene_analyzer import SceneAnalyzer
from alibi.camera_analysis_store import CameraAnalysis, get_camera_analysis_store
from alibi.known_persons import KnownPerson, KnownPersonsStore, get_known_persons_store
from alibi.continuous_learning import get_learning_system
from alibi.plates.plate_detect import PlateDetector
from alibi.plates.plate_ocr import PlateOCR
from alibi.plates.normalize import normalize_plate, format_plate_display
from alibi.plates.hotlist_store import HotlistStore
from alibi.plates.travel_detector import ImpossibleTravelDetector
from alibi.vehicles.sightings_store import VehicleSightingsStore, VehicleSighting
from alibi.cameras.camera_store import get_camera_store
from alibi.cameras.cross_camera import get_cross_camera_tracker

router = APIRouter(prefix="/camera", tags=["Enhanced Mobile Camera"])

# Alert deduplication: track last auto-alert to avoid spamming
_last_auto_alert_time: Optional[datetime] = None
_last_auto_alert_level: Optional[str] = None
AUTO_ALERT_COOLDOWN_SECONDS = 30

# Global instances
_gatekeeper = None
_tracker = None
_rule_evaluator = None
_incident_manager = None
_intelligence_store = None
_plate_detector = None
_plate_ocr = None
_hotlist_store = None
_sightings_store = None
_travel_detector = None
_camera_store = None
_cross_camera_tracker = None


def get_security_components():
    """Initialize security components"""
    global _gatekeeper, _tracker, _rule_evaluator, _incident_manager, _intelligence_store
    global _plate_detector, _plate_ocr, _hotlist_store, _sightings_store, _travel_detector
    global _camera_store, _cross_camera_tracker
    
    if _gatekeeper is None:
        policy = GatekeeperPolicy(min_combined_conf=0.5)
        _gatekeeper = VisionGatekeeper(model_path="yolov8n.pt", policy=policy)
    
    if _tracker is None:
        _tracker = MultiObjectTracker()
    
    if _rule_evaluator is None:
        # Load zones and rules
        import json
        from pathlib import Path
        zones_file = Path("alibi/data/config/zones.json")
        if zones_file.exists():
            with open(zones_file) as f:
                zones_config = json.load(f)
        else:
            zones_config = []
        
        _rule_evaluator = RuleEvaluator(zones_config)
    
    if _incident_manager is None:
        _incident_manager = IncidentManager(
            _rule_evaluator,
            auto_convert_to_training=True,
            camera_id="mobile"  # Default; overridden per-request with dynamic camera_id
        )
    
    if _intelligence_store is None:
        _intelligence_store = IntelligenceStore()

    if _plate_detector is None:
        _plate_detector = PlateDetector()

    if _plate_ocr is None:
        _plate_ocr = PlateOCR()

    if _hotlist_store is None:
        _hotlist_store = HotlistStore()

    if _sightings_store is None:
        _sightings_store = VehicleSightingsStore()

    if _travel_detector is None:
        _travel_detector = ImpossibleTravelDetector()

    if _camera_store is None:
        _camera_store = get_camera_store()

    if _cross_camera_tracker is None:
        _cross_camera_tracker = get_cross_camera_tracker()

    return _gatekeeper, _tracker, _rule_evaluator, _incident_manager, _intelligence_store


def _get_camera_id(username: str) -> str:
    """Get dynamic camera_id for a mobile user and register in camera store."""
    camera_id = f"mobile_{username}"
    _camera_store.upsert_mobile(camera_id, username)
    return camera_id


def assess_threat_level(detections, zone_hits, triggered_rules, ai_activities=None):
    """
    Assess threat level based on detections, rules, AND behavior.

    Unknown person != automatic threat. Threat depends on WHAT they're doing.

    Returns:
        (level: str, color: str, message: str)
        level: "safe", "caution", "warning", "critical"
    """
    # Start with safe
    level = "safe"
    color = "#10b981"  # Green
    message = "Scene is clear"

    if ai_activities is None:
        ai_activities = []

    # Check for WEAPONS - highest priority
    suspicious_objects = [d for d in detections if d.class_name in ["knife", "gun", "weapon"]]
    if suspicious_objects:
        level = "critical"
        color = "#dc2626"
        message = "⚠️ WEAPON DETECTED"
        return level, color, message

    # Check BEHAVIOR-BASED rules (these indicate actual threat)
    if triggered_rules:
        for track_id, rules in triggered_rules.items():
            # Aggressive or rapid movement
            if any("aggression" in r or "rapid" in r for r in rules):
                level = "warning"
                color = "#ef4444"
                message = "Aggressive movement detected"

            # Restricted zone breach (actual security violation)
            if any("restricted" in r for r in rules):
                level = "warning"
                color = "#ef4444"
                message = "Restricted zone breach"

            # Panic or crowd surge (actual emergency)
            if any("panic" in r or "crowd" in r for r in rules):
                level = "critical"
                color = "#dc2626"
                message = "Emergency situation - crowd/panic"

            # Loitering might be suspicious but not necessarily a threat
            if any("loitering" in r for r in rules):
                if level == "safe":
                    level = "caution"
                    color = "#f59e0b"
                    message = "Loitering detected"

    # Check AI-detected activities for suspicious behavior
    suspicious_activities = ["fighting", "running", "arguing", "breaking", "climbing"]
    detected_suspicious = [act for act in ai_activities if act.lower() in suspicious_activities]

    if detected_suspicious:
        if level == "safe":
            level = "caution"
            color = "#f59e0b"
            message = f"Suspicious activity: {', '.join(detected_suspicious)}"

    # Count people BUT don't automatically flag as threat
    # Multiple people is NORMAL and expected - not a threat by itself
    people = [d for d in detections if d.class_name == "person"]
    if len(people) > 0 and level == "safe":
        # Just informational, not a threat
        message = f"Monitoring {len(people)} person" + ("" if len(people) == 1 else "s")

    return level, color, message


@router.post("/analyze-secure")
async def analyze_frame_secure(
    image: UploadFile = File(...),
    current_user: User = Depends(get_current_user)
):
    """
    Analyze camera frame with security threat detection AND AI descriptions.
    
    Returns:
    - Detection results
    - Threat level assessment
    - Rule violations
    - AI natural language description (what the camera is seeing)
    - Recommended actions
    """
    # Get components
    gatekeeper, tracker, rule_evaluator, incident_manager, intelligence_store = get_security_components()

    # Dynamic camera_id based on logged-in user
    camera_id = _get_camera_id(current_user.username)

    # Read image
    contents = await image.read()
    nparr = np.frombuffer(contents, np.uint8)
    frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    
    if frame is None:
        raise HTTPException(status_code=400, detail="Invalid image")
    
    # Run gatekeeper (YOLO detection)
    timestamp = datetime.utcnow()
    result = gatekeeper.process_frame(frame, zones_config=None)
    
    # Update tracker (if eligible)
    tracks = {}
    triggered_rules = {}

    if result["eligible"]:
        # Run tracking
        from ultralytics import YOLO
        model = YOLO("yolov8n.pt")
        yolo_results = model.track(frame, persist=True, conf=0.5, verbose=False)
        tracks = tracker.update(yolo_results, zones_config=None, timestamp=timestamp)

        # Evaluate rules
        triggered_rules = rule_evaluator.evaluate(tracks)

        # Update incidents
        frame_number = int(timestamp.timestamp())
        incident_manager.update(tracks, frame_number, timestamp)

    # Get AI description of what camera is seeing FIRST (to get activities for threat assessment)
    ai_description_text = "Analysis in progress..."
    ai_confidence = 0.0
    ai_objects = []
    ai_activities = []

    try:
        scene_analyzer = SceneAnalyzer(mode="auto")
        # Try to get AI analysis
        ai_analysis = scene_analyzer.analyze_frame(frame)

        # SceneAnalyzer returns a dictionary
        ai_description_text = ai_analysis.get("description", "Analysis unavailable")
        ai_confidence = ai_analysis.get("confidence", 0.0)
        ai_objects = ai_analysis.get("detected_objects", [])
        ai_activities = ai_analysis.get("detected_activities", [])
    except Exception as e:
        # Fallback if AI analysis fails
        print(f"AI analysis failed: {e}")
        detections = result.get("detections", [])
        detected_classes = [d.class_name for d in detections]
        ai_description_text = f"Detected: {', '.join(detected_classes) if detected_classes else 'No objects'}. AI analysis temporarily unavailable."
        ai_confidence = 0.5

    # PLATE DETECTION: Detect and read license plates
    detected_plates = []
    hotlist_hit = False
    hotlist_reason = None
    try:
        raw_plates = _plate_detector.detect(frame)
        for plate in raw_plates:
            text, ocr_conf = _plate_ocr.read_plate(plate.plate_image)
            if text and ocr_conf >= 0.5:
                normalized = normalize_plate(text)
                display_text = format_plate_display(normalized) if normalized else text
                is_hotlist = _hotlist_store.is_on_hotlist(normalized)
                hl_reason = None
                if is_hotlist:
                    entry = _hotlist_store.get_by_plate(normalized)
                    hl_reason = entry.reason if entry else "unknown"
                    hotlist_hit = True
                    hotlist_reason = hl_reason

                detected_plates.append({
                    "text": normalized or text,
                    "display": display_text,
                    "confidence": round(min(plate.confidence, ocr_conf), 2),
                    "bbox": list(plate.bbox),
                    "hotlist_match": is_hotlist,
                    "hotlist_reason": hl_reason,
                })

                # Record sighting
                _sightings_store.add_sighting(VehicleSighting(
                    sighting_id=str(uuid.uuid4()),
                    camera_id=camera_id,
                    ts=timestamp.isoformat(),
                    bbox=plate.bbox,
                    color="unknown",
                    make="unknown",
                    model="unknown",
                    confidence=round(min(plate.confidence, ocr_conf), 2),
                    metadata={"plate_text": normalized or text, "ocr_confidence": ocr_conf},
                ))

                # Cross-camera correlation
                cross_alerts = _cross_camera_tracker.record_sighting(
                    camera_id=camera_id,
                    entity_type="plate",
                    entity_id=normalized or text,
                    timestamp=timestamp.isoformat(),
                    metadata={"confidence": ocr_conf},
                )
                for ca in cross_alerts:
                    detected_plates[-1].setdefault("cross_camera_alerts", []).append({
                        "type": ca.alert_type,
                        "message": ca.message,
                        "cameras": ca.cameras,
                    })
                    hotlist_hit = True
                    hotlist_reason = ca.message

                # Check impossible travel (legacy single-detector)
                travel_alert = _travel_detector.check(
                    normalized or text, camera_id, timestamp.isoformat()
                )
                if travel_alert:
                    detected_plates[-1]["impossible_travel"] = {
                        "alert": True,
                        "message": travel_alert.message,
                        "previous_camera": travel_alert.camera_a,
                        "seconds_between": travel_alert.seconds_between,
                    }
                    hotlist_hit = True
                    hotlist_reason = travel_alert.message
    except Exception as e:
        print(f"[PlateDetection] Error: {e}")

    # NOW assess threat level with AI activities
    detections = result.get("detections", [])
    threat_level, threat_color, threat_message = assess_threat_level(
        detections,
        result.get("zone_hits", []),
        triggered_rules,
        ai_activities  # Pass activities to threat assessment
    )

    # Escalate threat if hotlist plate detected
    if hotlist_hit and threat_level in ("safe", "caution"):
        threat_level = "warning"
        threat_color = "#ef4444"
        threat_message = f"HOTLIST PLATE MATCH: {detected_plates[0]['display']} — {hotlist_reason}"

    # CONTINUOUS LEARNING: Get additional threat intelligence
    learning_system = get_learning_system()
    threat_enhancement = learning_system.get_threat_assessment_enhancement(ai_description_text)

    # Store analysis for history
    try:
        analysis_store = get_camera_analysis_store()
        username = current_user.username if current_user else "unknown"

        analysis_entry = CameraAnalysis(
            analysis_id=str(uuid.uuid4()),
            timestamp=timestamp.isoformat(),
            user=username,
            camera_source=camera_id,
            description=ai_description_text,
            confidence=ai_confidence,
            detected_objects=ai_objects,
            detected_activities=ai_activities,
            safety_concern=threat_level in ["warning", "critical"],
            method="openai_vision",  # Hardcode since ai_analysis not in scope
            metadata={
                "threat_level": threat_level,
                "threat_message": threat_message if threat_level in ["warning", "critical"] else None,
                "detections_count": len(detections),
                "tracks_count": len(tracks)
            }
        )

        # Save snapshot and add paths to analysis
        snapshot_path, thumbnail_path = analysis_store.save_snapshot(frame, analysis_entry.analysis_id)
        analysis_entry.snapshot_path = snapshot_path
        analysis_entry.thumbnail_path = thumbnail_path

        analysis_store.add_analysis(analysis_entry)
    except Exception as e:
        print(f"Failed to store analysis: {e}")

    # AUTO-ALERT: Create persistent alert for dangerous detections
    alert_created = False
    if threat_level in ("warning", "critical"):
        alert_created = _maybe_create_auto_alert(
            threat_level=threat_level,
            threat_message=threat_message,
            ai_description=ai_description_text,
            snapshot_path=getattr(analysis_entry, 'snapshot_path', None) if 'analysis_entry' in dir() else None,
            analysis_id=analysis_entry.analysis_id if 'analysis_entry' in dir() else None,
            username=current_user.username,
            timestamp=timestamp,
            ai_activities=ai_activities,
        )

    # Build response
    return {
        "timestamp": timestamp.isoformat(),
        "detections": {
            "objects": [{"class": d.class_name, "confidence": d.confidence} for d in detections],
            "count": len(detections),
            "security_relevant": result.get("security_relevant", False)
        },
        "threat": {
            "level": threat_level,
            "color": threat_color,
            "message": threat_message,
            "learned_enhancement": threat_enhancement  # Add learned intelligence
        },
        "tracking": {
            "active_tracks": len(tracks),
            "triggered_rules": triggered_rules
        },
        "ai_description": {
            "description": ai_description_text,
            "confidence": ai_confidence,
            "objects": ai_objects,
            "activities": ai_activities
        },
        "plates": {
            "detected": detected_plates,
            "count": len(detected_plates),
        },
        "scores": result.get("scores", {}),
        "eligible_for_training": result.get("eligible", False),
        "alert_created": alert_created
    }


def _maybe_create_auto_alert(
    threat_level: str,
    threat_message: str,
    ai_description: str,
    snapshot_path: Optional[str],
    analysis_id: Optional[str],
    username: str,
    timestamp: datetime,
    ai_activities: list,
) -> bool:
    """Create a persistent RedFlag alert if cooldown has elapsed. Returns True if alert was created."""
    global _last_auto_alert_time, _last_auto_alert_level

    # Dedup: skip if same threat level within cooldown window
    if _last_auto_alert_time and _last_auto_alert_level == threat_level:
        elapsed = (timestamp - _last_auto_alert_time).total_seconds()
        if elapsed < AUTO_ALERT_COOLDOWN_SECONDS:
            return False

    try:
        severity_map = {"warning": "high", "critical": "critical"}
        category = "suspicious_activity"
        if "weapon" in threat_message.lower():
            category = "suspicious_person"

        flag = RedFlag(
            flag_id=f"auto_{uuid.uuid4().hex[:12]}",
            timestamp=timestamp.isoformat(),
            created_by=f"system/{username}",
            severity=severity_map.get(threat_level, "high"),
            category=category,
            description=f"[AUTO] {threat_message} — {ai_description}",
            snapshot_url=snapshot_path,
            analysis_id=analysis_id,
            location=f"mobile_{username}",
            tags=["auto_alert", f"threat_{threat_level}"] + [a.lower() for a in ai_activities[:5]],
            metadata={
                "threat_level": threat_level,
                "threat_message": threat_message,
                "ai_description": ai_description,
                "source": "camera_auto_alert",
            },
            resolved=False,
            resolved_by=None,
            resolved_at=None,
            resolution_notes=None,
        )

        store = IntelligenceStore()
        store.add_red_flag(flag)

        _last_auto_alert_time = timestamp
        _last_auto_alert_level = threat_level
        print(f"[AutoAlert] Created {threat_level} alert: {threat_message}")
        return True

    except Exception as e:
        print(f"[AutoAlert] Failed to create alert: {e}")
        return False


@router.post("/red-flag")
async def create_red_flag(
    data: dict = Body(...),
    current_user: User = Depends(get_current_user)
):
    """
    Create a red flag from camera feed.
    
    User can flag anything suspicious they see in real-time.
    """
    _, _, _, _, intelligence_store = get_security_components()
    
    # Save snapshot if provided
    snapshot_path = None
    snapshot_data = data.get("snapshot_path")
    if snapshot_data and snapshot_data.startswith("data:image"):
        try:
            # Extract base64 data
            import base64
            from pathlib import Path
            
            header, encoded = snapshot_data.split(",", 1)
            image_data = base64.b64decode(encoded)
            
            # Save to red_flags directory
            red_flags_dir = Path("alibi/data/red_flags")
            red_flags_dir.mkdir(parents=True, exist_ok=True)
            
            flag_id = str(uuid.uuid4())
            snapshot_filename = f"{flag_id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.jpg"
            snapshot_path_full = red_flags_dir / snapshot_filename
            
            with open(snapshot_path_full, "wb") as f:
                f.write(image_data)
            
            snapshot_path = str(snapshot_path_full)
            print(f"✅ Saved red flag snapshot: {snapshot_path}")
        except Exception as e:
            print(f"⚠️  Failed to save red flag snapshot: {e}")
            snapshot_path = "snapshot_save_failed"
    
    red_flag = RedFlag(
        flag_id=str(uuid.uuid4()),
        timestamp=datetime.utcnow(),
        camera_id=data.get("camera_id", f"mobile_{current_user.username}"),
        flagged_by=current_user.username,
        severity=data.get("severity", "medium"),
        category=data.get("category", "suspicious_activity"),
        description=data.get("description", ""),
        snapshot_path=snapshot_path,
        notes=data.get("notes", "")
    )
    
    intelligence_store.add_red_flag(red_flag)

    # CONTINUOUS LEARNING: Learn from this red flag
    learning_system = get_learning_system()
    learning_system.learn_from_red_flag(
        category=red_flag.category,
        description=red_flag.description,
        severity=red_flag.severity
    )

    print(f"✅ Red flag created: {red_flag.flag_id} by {current_user.username}")

    return {
        "success": True,
        "flag_id": red_flag.flag_id,
        "message": "Red flag created successfully"
    }


@router.get("/alerts")
async def get_camera_alerts(
    limit: int = 20,
    current_user: User = Depends(get_current_user)
):
    """Get recent camera alerts (auto-generated and manual red flags)."""
    store = IntelligenceStore()
    flags = store.get_red_flags(limit=limit)
    # Return most recent first, as list of dicts
    return [asdict(f) for f in reversed(flags[-limit:])]


@router.post("/tag-person")
async def tag_person(
    data: dict = Body(...),
    current_user: User = Depends(get_current_user)
):
    """
    Tag a person as known with identity information.

    Allows marking people as "good" (trusted) or "bad" (watch/unauthorized).
    """
    persons_store = get_known_persons_store()

    # Save snapshot if provided
    reference_image_path = None
    snapshot_data = data.get("snapshot")
    if snapshot_data and snapshot_data.startswith("data:image"):
        try:
            # Extract base64 data
            from pathlib import Path

            header, encoded = snapshot_data.split(",", 1)
            image_data = base64.b64decode(encoded)

            # Save to known_persons directory
            persons_dir = Path("alibi/data/known_persons")
            persons_dir.mkdir(parents=True, exist_ok=True)

            person_id = str(uuid.uuid4())
            snapshot_filename = f"{person_id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.jpg"
            snapshot_path_full = persons_dir / snapshot_filename

            with open(snapshot_path_full, "wb") as f:
                f.write(image_data)

            reference_image_path = str(snapshot_path_full)
            print(f"✅ Saved person reference image: {reference_image_path}")
        except Exception as e:
            print(f"⚠️  Failed to save person reference image: {e}")
            reference_image_path = None

    # Create KnownPerson
    person_id = str(uuid.uuid4())
    trust_level = data.get("trust_level", "neutral")  # "trusted", "neutral", "watch"

    # Map "good"/"bad" to trust levels
    if data.get("is_good") == True or trust_level == "good":
        trust_level = "trusted"
        is_authorized = True
    elif data.get("is_bad") == True or trust_level == "bad":
        trust_level = "watch"
        is_authorized = False
    else:
        is_authorized = data.get("is_authorized", True)

    person = KnownPerson(
        person_id=person_id,
        name=data.get("name", "Unknown Person"),
        role=data.get("role", "visitor"),  # "resident", "visitor", "staff", "family", "security", "delivery", "other"
        description=data.get("description", ""),
        added_by=current_user.username,
        added_at=datetime.utcnow().isoformat(),
        reference_image_path=reference_image_path,
        notes=data.get("notes", ""),
        is_authorized=is_authorized,
        trust_level=trust_level
    )

    persons_store.add_person(person)

    # CONTINUOUS LEARNING: Learn from this person tagging
    learning_system = get_learning_system()
    learning_system.learn_from_person_tag(
        person_name=person.name,
        person_role=person.role,
        description=person.description,
        trust_level=trust_level
    )

    return {
        "success": True,
        "person_id": person.person_id,
        "message": f"Person '{person.name}' tagged as {trust_level}"
    }


@router.get("/known-persons")
async def get_known_persons(
    current_user: User = Depends(get_current_user)
):
    """
    Get all known persons.
    """
    persons_store = get_known_persons_store()
    persons = persons_store.get_all_persons()

    return {
        "persons": [p.to_dict() for p in persons],
        "count": len(persons)
    }


@router.get("/known-persons/{person_id}")
async def get_person(
    person_id: str,
    current_user: User = Depends(get_current_user)
):
    """
    Get a specific person by ID.
    """
    persons_store = get_known_persons_store()
    person = persons_store.get_person(person_id)

    if not person:
        raise HTTPException(status_code=404, detail="Person not found")

    return person.to_dict()


@router.put("/known-persons/{person_id}")
async def update_person(
    person_id: str,
    data: dict = Body(...),
    current_user: User = Depends(get_current_user)
):
    """
    Update a person's information (e.g., change trust level, mark as good/bad).
    """
    persons_store = get_known_persons_store()

    # Map "good"/"bad" to trust levels
    updates = data.copy()
    if "is_good" in updates:
        if updates["is_good"]:
            updates["trust_level"] = "trusted"
            updates["is_authorized"] = True
        del updates["is_good"]

    if "is_bad" in updates:
        if updates["is_bad"]:
            updates["trust_level"] = "watch"
            updates["is_authorized"] = False
        del updates["is_bad"]

    success = persons_store.update_person(person_id, updates)

    if not success:
        raise HTTPException(status_code=404, detail="Person not found")

    return {
        "success": True,
        "message": "Person updated successfully"
    }


@router.delete("/known-persons/{person_id}")
async def remove_person(
    person_id: str,
    current_user: User = Depends(get_current_user)
):
    """
    Remove a person (soft delete - marks as unauthorized).
    """
    persons_store = get_known_persons_store()
    success = persons_store.remove_person(person_id)

    if not success:
        raise HTTPException(status_code=404, detail="Person not found")

    return {
        "success": True,
        "message": "Person removed successfully"
    }


@router.get("/secure-stream", response_class=HTMLResponse)
async def secure_mobile_stream():
    """Enhanced mobile camera stream with threat detection"""
    return HTMLResponse(content=SECURE_CAMERA_HTML)


# Enhanced HTML with threat warnings and red flag
SECURE_CAMERA_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Alibi Security Camera</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #1a1a1a;
            color: white;
            overflow-x: hidden;
        }
        
        .header {
            background: #000;
            padding: 15px;
            text-align: center;
            border-bottom: 2px solid #333;
        }
        
        .header h1 {
            font-size: 20px;
            color: #10b981;
        }
        
        .video-container {
            position: relative;
            width: 100%;
            max-width: 640px;
            margin: 20px auto;
            background: #000;
            border-radius: 10px;
            overflow: hidden;
            box-shadow: 0 10px 40px rgba(0,0,0,0.5);
        }
        
        video {
            width: 100%;
            height: auto;
            display: block;
        }
        
        .threat-overlay {
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            padding: 15px;
            background: linear-gradient(180deg, rgba(0,0,0,0.8) 0%, transparent 100%);
            z-index: 10;
        }
        
        .threat-indicator {
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 12px;
            border-radius: 8px;
            font-weight: bold;
            font-size: 14px;
            transition: all 0.3s;
        }
        
        .threat-safe {
            background: rgba(16, 185, 129, 0.2);
            border: 2px solid #10b981;
            color: #10b981;
        }
        
        .threat-caution {
            background: rgba(245, 158, 11, 0.2);
            border: 2px solid #f59e0b;
            color: #f59e0b;
        }
        
        .threat-warning {
            background: rgba(239, 68, 68, 0.2);
            border: 2px solid #ef4444;
            color: #ef4444;
            animation: pulse 2s infinite;
        }
        
        .threat-critical {
            background: rgba(220, 38, 38, 0.3);
            border: 2px solid #dc2626;
            color: #fff;
            animation: pulse 1s infinite;
        }
        
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.7; }
        }
        
        .detection-info {
            position: absolute;
            bottom: 0;
            left: 0;
            right: 0;
            padding: 15px;
            background: linear-gradient(0deg, rgba(0,0,0,0.95) 0%, transparent 100%);
            z-index: 10;
        }
        
        .ai-description {
            background: rgba(16, 185, 129, 0.2);
            border: 1px solid rgba(16, 185, 129, 0.5);
            padding: 12px;
            border-radius: 8px;
            margin-bottom: 10px;
            font-size: 14px;
            line-height: 1.4;
            max-height: 80px;
            overflow-y: auto;
        }
        
        .ai-description strong {
            color: #10b981;
            display: block;
            margin-bottom: 4px;
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        
        .analyzing {
            animation: pulse 1.5s ease-in-out infinite;
        }
        
        @keyframes pulse {
            0%, 100% { opacity: 0.6; }
            50% { opacity: 1; }
        }
        
        .status-dot {
            display: inline-block;
            width: 8px;
            height: 8px;
            border-radius: 50%;
            margin-right: 8px;
            background: #10b981;
            animation: blink 2s infinite;
        }
        
        @keyframes blink {
            0%, 50%, 100% { opacity: 1; }
            25%, 75% { opacity: 0.3; }
        }
        
        .detection-stats {
            display: flex;
            gap: 15px;
            font-size: 12px;
        }
        
        .stat {
            background: rgba(255,255,255,0.1);
            padding: 6px 12px;
            border-radius: 6px;
        }
        
        .controls {
            padding: 20px;
            max-width: 640px;
            margin: 0 auto;
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
        }
        
        button {
            flex: 1;
            padding: 15px;
            border: none;
            border-radius: 8px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s;
        }
        
        #pause-btn, #red-flag-btn, #tag-person-btn {
            display: none;
        }
        
        .btn-primary {
            background: #10b981;
            color: white;
        }
        
        .btn-danger {
            background: #ef4444;
            color: white;
        }
        
        .btn-secondary {
            background: #374151;
            color: white;
        }
        
        button:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(0,0,0,0.3);
        }
        
        .red-flag-btn {
            background: #dc2626;
            color: white;
            font-size: 18px;
            animation: glow 2s infinite;
        }

        @keyframes glow {
            0%, 100% { box-shadow: 0 0 5px #dc2626; }
            50% { box-shadow: 0 0 20px #dc2626; }
        }

        .tag-person-btn {
            background: #3b82f6;
            color: white;
            font-size: 16px;
        }

        .trust-buttons {
            display: flex;
            gap: 10px;
            margin: 15px 0;
        }

        .trust-btn {
            flex: 1;
            padding: 12px;
            border: 2px solid transparent;
            border-radius: 8px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s;
        }

        .trust-btn.selected {
            border-color: white;
            transform: scale(1.05);
        }

        .trust-good {
            background: #10b981;
            color: white;
        }

        .trust-neutral {
            background: #6b7280;
            color: white;
        }

        .trust-bad {
            background: #ef4444;
            color: white;
        }

        .form-group input {
            width: 100%;
            padding: 10px;
            border: 1px solid #374151;
            border-radius: 8px;
            background: #111827;
            color: white;
            font-size: 14px;
        }
        
        .modal {
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0,0,0,0.8);
            z-index: 1000;
            align-items: center;
            justify-content: center;
        }
        
        .modal.active { display: flex; }
        
        .modal-content {
            background: #1f2937;
            padding: 30px;
            border-radius: 15px;
            max-width: 500px;
            width: 90%;
        }
        
        .modal h3 {
            color: #ef4444;
            margin-bottom: 20px;
        }
        
        .form-group {
            margin-bottom: 15px;
        }
        
        .form-group label {
            display: block;
            margin-bottom: 8px;
            color: #d1d5db;
        }
        
        .form-group select,
        .form-group textarea {
            width: 100%;
            padding: 10px;
            border: 1px solid #374151;
            border-radius: 8px;
            background: #111827;
            color: white;
            font-size: 14px;
        }
        
        .modal-actions {
            display: flex;
            gap: 10px;
            margin-top: 20px;
        }

        /* === ALERT SYSTEM === */
        #alert-banner {
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            z-index: 1000;
            padding: 12px 16px;
            background: #dc2626;
            color: white;
            font-weight: 600;
            font-size: 14px;
            animation: alertPulse 1s infinite;
            cursor: pointer;
        }
        #alert-banner .alert-content {
            display: flex;
            align-items: center;
            justify-content: space-between;
            max-width: 640px;
            margin: 0 auto;
        }
        #alert-banner .alert-text { flex: 1; }
        #alert-banner .alert-dismiss {
            background: rgba(255,255,255,0.2);
            border: none;
            color: white;
            padding: 4px 12px;
            border-radius: 4px;
            font-size: 12px;
            cursor: pointer;
            margin-left: 12px;
        }
        @keyframes alertPulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.85; }
        }

        #alert-badge {
            display: none;
            position: fixed;
            top: 60px;
            right: 16px;
            z-index: 999;
            background: #dc2626;
            color: white;
            width: 32px;
            height: 32px;
            border-radius: 50%;
            font-size: 14px;
            font-weight: bold;
            line-height: 32px;
            text-align: center;
            cursor: pointer;
            box-shadow: 0 2px 8px rgba(220,38,38,0.5);
        }

        #alert-history {
            display: none;
            position: fixed;
            top: 0;
            right: 0;
            bottom: 0;
            width: 340px;
            max-width: 90vw;
            background: #111;
            border-left: 2px solid #333;
            z-index: 1001;
            overflow-y: auto;
            padding: 16px;
        }
        #alert-history h3 {
            font-size: 16px;
            margin-bottom: 12px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        #alert-history .close-btn {
            background: #333;
            border: none;
            color: white;
            padding: 4px 10px;
            border-radius: 4px;
            cursor: pointer;
        }
        .alert-item {
            background: #1a1a1a;
            border-left: 3px solid #ef4444;
            padding: 10px 12px;
            margin-bottom: 8px;
            border-radius: 0 6px 6px 0;
            font-size: 13px;
        }
        .alert-item.severity-critical { border-left-color: #dc2626; }
        .alert-item.severity-high { border-left-color: #ef4444; }
        .alert-item .alert-time {
            font-size: 11px;
            color: #888;
            margin-bottom: 4px;
        }
        .alert-item .alert-desc { line-height: 1.4; }

        /* === PLATE DETECTION === */
        #plate-display {
            display: none;
            max-width: 640px;
            margin: 0 auto 10px;
            padding: 0 20px;
        }
        .plate-box {
            background: #111827;
            border: 2px solid #3b82f6;
            border-radius: 8px;
            padding: 12px;
        }
        .plate-box.hotlist-match {
            border-color: #ef4444;
            background: rgba(239, 68, 68, 0.1);
            animation: pulse 1.5s infinite;
        }
        .plate-header {
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            color: #3b82f6;
            margin-bottom: 8px;
            font-weight: 600;
        }
        .plate-box.hotlist-match .plate-header { color: #ef4444; }
        .plate-item {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 6px 0;
            border-bottom: 1px solid #333;
        }
        .plate-item:last-child { border-bottom: none; }
        .plate-text {
            font-family: 'Courier New', monospace;
            font-size: 20px;
            font-weight: bold;
            letter-spacing: 2px;
            color: white;
        }
        .plate-confidence {
            font-size: 11px;
            color: #9ca3af;
            background: rgba(255,255,255,0.05);
            padding: 2px 8px;
            border-radius: 4px;
        }
        .plate-hotlist-warning {
            color: #ef4444;
            font-size: 12px;
            font-weight: 600;
            margin-top: 6px;
        }
    </style>
</head>
<body>
    <!-- Alert Banner (fixed top, hidden by default) -->
    <div id="alert-banner" onclick="toggleAlertHistory()">
        <div class="alert-content">
            <span class="alert-text" id="alert-banner-text">ALERT</span>
            <button class="alert-dismiss" onclick="event.stopPropagation(); dismissBanner()">Dismiss</button>
        </div>
    </div>

    <!-- Alert count badge -->
    <div id="alert-badge" onclick="toggleAlertHistory()">0</div>

    <!-- Alert History Panel -->
    <div id="alert-history">
        <h3>
            Alerts
            <button class="close-btn" onclick="toggleAlertHistory()">Close</button>
        </h3>
        <div id="alert-list">
            <p style="color:#666; font-size:13px;">No alerts yet</p>
        </div>
    </div>

    <div class="header">
        <h1>🔒 ALIBI SECURITY CAMERA</h1>
    </div>

    <div class="video-container">
        <div class="threat-overlay">
            <div class="threat-indicator threat-safe" id="threat-indicator">
                <span id="threat-icon">✓</span>
                <span id="threat-message">No threats detected</span>
            </div>
        </div>
        
        <video id="video" autoplay playsinline></video>
        
        <div class="detection-info">
            <div class="ai-description" id="ai-description">
                <strong><span class="status-dot"></span>AI Vision:</strong>
                <span id="ai-text">Starting camera...</span>
            </div>
            <div class="detection-stats">
                <div class="stat">
                    <strong id="object-count">0</strong> objects
                </div>
                <div class="stat">
                    <strong id="track-count">0</strong> tracks
                </div>
                <div class="stat" id="security-status">
                    Monitoring...
                </div>
            </div>
        </div>
    </div>
    
    <!-- Plate Detection Display (hidden until plates detected) -->
    <div id="plate-display">
        <div class="plate-box" id="plate-box">
            <div class="plate-header" id="plate-header">License Plates Detected</div>
            <div id="plate-list"></div>
        </div>
    </div>

    <div class="controls">
        <button class="btn-primary" id="start-btn">▶️ Start Camera</button>
        <button class="btn-secondary" id="pause-btn">⏸ Pause</button>
        <button class="tag-person-btn" id="tag-person-btn">👤 Tag Person</button>
        <button class="red-flag-btn" id="red-flag-btn">🚩 RED FLAG</button>
    </div>
    
    <!-- Red Flag Modal -->
    <div class="modal" id="red-flag-modal">
        <div class="modal-content">
            <h3>🚩 Create Red Flag</h3>
            <div class="form-group">
                <label>Severity</label>
                <select id="severity">
                    <option value="low">Low</option>
                    <option value="medium" selected>Medium</option>
                    <option value="high">High</option>
                    <option value="critical">Critical</option>
                </select>
            </div>
            <div class="form-group">
                <label>Category</label>
                <select id="category">
                    <option value="suspicious_activity">Suspicious Activity</option>
                    <option value="security_breach">Security Breach</option>
                    <option value="unusual_behavior">Unusual Behavior</option>
                    <option value="potential_threat">Potential Threat</option>
                    <option value="other">Other</option>
                </select>
            </div>
            <div class="form-group">
                <label>Description</label>
                <textarea id="description" rows="4" placeholder="What did you see?"></textarea>
            </div>
            <div class="modal-actions">
                <button class="btn-secondary" onclick="closeRedFlagModal()">Cancel</button>
                <button class="btn-danger" onclick="submitRedFlag()">Submit Red Flag</button>
            </div>
        </div>
    </div>

    <!-- Tag Person Modal -->
    <div class="modal" id="tag-person-modal">
        <div class="modal-content">
            <h3>👤 Tag Person</h3>

            <div class="form-group">
                <label>Trust Level</label>
                <div class="trust-buttons">
                    <button class="trust-btn trust-good selected" onclick="selectTrustLevel('good')" id="trust-good">
                        ✅ Good
                    </button>
                    <button class="trust-btn trust-neutral" onclick="selectTrustLevel('neutral')" id="trust-neutral">
                        ➖ Neutral
                    </button>
                    <button class="trust-btn trust-bad" onclick="selectTrustLevel('bad')" id="trust-bad">
                        ⚠️ Bad
                    </button>
                </div>
            </div>

            <div class="form-group">
                <label>Name</label>
                <input type="text" id="person-name" placeholder="Enter person's name">
            </div>

            <div class="form-group">
                <label>Role</label>
                <select id="person-role">
                    <option value="visitor">Visitor</option>
                    <option value="resident">Resident</option>
                    <option value="staff">Staff</option>
                    <option value="family">Family</option>
                    <option value="security">Security</option>
                    <option value="delivery">Delivery</option>
                    <option value="other">Other</option>
                </select>
            </div>

            <div class="form-group">
                <label>Description (Physical appearance)</label>
                <textarea id="person-description" rows="3" placeholder="E.g., Wearing blue shirt, tall, glasses..."></textarea>
            </div>

            <div class="form-group">
                <label>Notes (Optional)</label>
                <textarea id="person-notes" rows="2" placeholder="Additional information..."></textarea>
            </div>

            <div class="modal-actions">
                <button class="btn-secondary" onclick="closeTagPersonModal()">Cancel</button>
                <button class="btn-primary" onclick="submitTagPerson()">Tag Person</button>
            </div>
        </div>
    </div>

    <script>
        const video = document.getElementById('video');
        const token = localStorage.getItem('alibi_token');
        let stream = null;
        let isPaused = false;
        let lastSnapshot = null;
        let selectedTrustLevel = 'good';  // Default trust level
        
        if (!token) {
            window.location.href = '/camera/login';
        }
        
        async function startCamera() {
            console.log('startCamera function called');

            try {
                console.log('Requesting camera access...');
                stream = await navigator.mediaDevices.getUserMedia({
                    video: { facingMode: 'environment', width: 640, height: 480 }
                });
                console.log('Camera access granted, stream:', stream);

                video.srcObject = stream;
                console.log('Video srcObject set');

                // Hide start button, show pause and action buttons
                document.getElementById('start-btn').style.display = 'none';
                document.getElementById('pause-btn').style.display = 'block';
                document.getElementById('tag-person-btn').style.display = 'block';
                document.getElementById('red-flag-btn').style.display = 'block';
                console.log('Buttons updated');

                // Start analysis loop
                setInterval(analyzeFrame, 4000);  // Every 4 seconds (reduced frequency)
                console.log('Analysis loop started');
            } catch (error) {
                console.error('Camera error:', error);
                alert('Camera access denied: ' + error.message);
            }
        }
        
        let isAnalyzing = false;
        let analysisTimeout = null;
        
        async function analyzeFrame() {
            if (isPaused || !stream || isAnalyzing) return;

            isAnalyzing = true;

            // Get references (but don't change text - keep previous description visible)
            const aiText = document.getElementById('ai-text');
            const aiDescription = document.getElementById('ai-description');
            // Add subtle visual feedback that analysis is happening
            aiDescription.classList.add('analyzing');

            // Capture frame
            const canvas = document.createElement('canvas');
            canvas.width = video.videoWidth;
            canvas.height = video.videoHeight;
            const ctx = canvas.getContext('2d');
            ctx.drawImage(video, 0, 0);
            
            // Set timeout to prevent hanging (25 seconds)
            analysisTimeout = setTimeout(() => {
                if (isAnalyzing) {
                    document.getElementById('ai-description').classList.remove('analyzing');
                    aiText.textContent = 'Analysis timed out - retrying next frame...';
                    aiText.style.color = '#f59e0b';
                    isAnalyzing = false;
                }
            }, 25000);
            
            // Convert to blob
            canvas.toBlob(async (blob) => {
                const formData = new FormData();
                formData.append('image', blob, 'frame.jpg');
                
                try {
                    const controller = new AbortController();
                    const timeoutId = setTimeout(() => controller.abort(), 20000);
                    
                    const response = await fetch('/camera/analyze-secure', {
                        method: 'POST',
                        headers: { 'Authorization': `Bearer ${token}` },
                        body: formData,
                        signal: controller.signal
                    });
                    
                    clearTimeout(timeoutId);
                    clearTimeout(analysisTimeout);
                    
                    if (!response.ok) {
                        throw new Error(`HTTP ${response.status}`);
                    }
                    
                    const result = await response.json();
                    aiText.style.fontStyle = 'normal';
                    aiText.style.color = 'white';
                    aiDescription.classList.remove('analyzing');
                    updateThreatDisplay(result);
                    lastSnapshot = canvas.toDataURL('image/jpeg');
                    isAnalyzing = false;
                } catch (error) {
                    clearTimeout(analysisTimeout);
                    aiDescription.classList.remove('analyzing');
                    console.error('Analysis failed:', error);
                    
                    if (error.name === 'AbortError') {
                        aiText.textContent = 'Request timed out - continuing...';
                    } else {
                        aiText.textContent = 'Analysis error - continuing...';
                    }
                    aiText.style.color = '#f59e0b';
                    isAnalyzing = false;
                }
            }, 'image/jpeg');
        }
        
        function updateThreatDisplay(result) {
            const indicator = document.getElementById('threat-indicator');
            const icon = document.getElementById('threat-icon');
            const message = document.getElementById('threat-message');
            const objectCount = document.getElementById('object-count');
            const trackCount = document.getElementById('track-count');
            const securityStatus = document.getElementById('security-status');
            const aiText = document.getElementById('ai-text');
            
            // Update threat level
            const threat = result.threat;
            indicator.className = `threat-indicator threat-${threat.level}`;
            message.textContent = threat.message;
            
            // Update icon
            if (threat.level === 'safe') icon.textContent = '✓';
            else if (threat.level === 'caution') icon.textContent = '⚠️';
            else if (threat.level === 'warning') icon.textContent = '🔴';
            else icon.textContent = '🚨';
            
            // Update AI description
            if (result.ai_description && result.ai_description.description) {
                aiText.textContent = result.ai_description.description;
                
                // Highlight safety concerns
                if (threat.level === 'warning' || threat.level === 'critical') {
                    document.getElementById('ai-description').style.borderColor = threat.color;
                    document.getElementById('ai-description').style.background = `${threat.color}22`;
                } else {
                    document.getElementById('ai-description').style.borderColor = 'rgba(16, 185, 129, 0.5)';
                    document.getElementById('ai-description').style.background = 'rgba(16, 185, 129, 0.2)';
                }
            }
            
            // Update stats
            objectCount.textContent = result.detections.count;
            trackCount.textContent = result.tracking.active_tracks;
            
            if (result.detections.security_relevant) {
                securityStatus.textContent = 'Security Alert';
                securityStatus.style.color = '#ef4444';
            } else {
                securityStatus.textContent = 'Monitoring...';
                securityStatus.style.color = '#10b981';
            }
        }
        
        function openRedFlagModal() {
            document.getElementById('red-flag-modal').classList.add('active');
        }
        
        function closeRedFlagModal() {
            document.getElementById('red-flag-modal').classList.remove('active');
        }
        
        async function submitRedFlag() {
            if (!lastSnapshot) {
                alert('No snapshot available. Please wait for camera analysis to complete.');
                return;
            }
            
            const description = document.getElementById('description').value.trim();
            if (!description) {
                alert('Please enter a description of what you saw.');
                return;
            }
            
            const data = {
                severity: document.getElementById('severity').value,
                category: document.getElementById('category').value,
                description: description,
                camera_id: 'mobile_' + (localStorage.getItem('alibi_user') ? JSON.parse(localStorage.getItem('alibi_user')).username : 'unknown'),
                snapshot_path: lastSnapshot
            };
            
            try {
                const response = await fetch('/camera/red-flag', {
                    method: 'POST',
                    headers: {
                        'Authorization': `Bearer ${token}`,
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify(data)
                });
                
                if (!response.ok) {
                    const errorText = await response.text();
                    throw new Error(`HTTP ${response.status}: ${errorText}`);
                }
                
                const result = await response.json();
                
                if (result.success) {
                    alert('🚩 Red flag created successfully!');
                    closeRedFlagModal();
                    document.getElementById('description').value = '';
                } else {
                    alert('Failed to create red flag: ' + (result.message || 'Unknown error'));
                }
            } catch (error) {
                console.error('Red flag error:', error);
                alert('Failed to create red flag: ' + error.message);
            }
        }

        // Tag Person Functions
        function selectTrustLevel(level) {
            selectedTrustLevel = level;
            // Remove selected class from all
            document.getElementById('trust-good').classList.remove('selected');
            document.getElementById('trust-neutral').classList.remove('selected');
            document.getElementById('trust-bad').classList.remove('selected');
            // Add to selected
            document.getElementById(`trust-${level}`).classList.add('selected');
        }

        function openTagPersonModal() {
            // Reset form
            document.getElementById('person-name').value = '';
            document.getElementById('person-role').value = 'visitor';
            document.getElementById('person-description').value = '';
            document.getElementById('person-notes').value = '';
            selectTrustLevel('good');  // Reset to default

            document.getElementById('tag-person-modal').classList.add('active');
        }

        function closeTagPersonModal() {
            document.getElementById('tag-person-modal').classList.remove('active');
        }

        async function submitTagPerson() {
            if (!lastSnapshot) {
                alert('No snapshot available. Please wait for camera analysis to complete.');
                return;
            }

            const name = document.getElementById('person-name').value.trim();
            if (!name) {
                alert("Please enter the person's name.");
                return;
            }

            const description = document.getElementById('person-description').value.trim();
            if (!description) {
                alert("Please enter a physical description.");
                return;
            }

            const data = {
                name: name,
                role: document.getElementById('person-role').value,
                description: description,
                notes: document.getElementById('person-notes').value.trim(),
                trust_level: selectedTrustLevel,
                snapshot: lastSnapshot
            };

            try {
                const response = await fetch('/camera/tag-person', {
                    method: 'POST',
                    headers: {
                        'Authorization': `Bearer ${token}`,
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify(data)
                });

                if (!response.ok) {
                    const errorText = await response.text();
                    throw new Error(`HTTP ${response.status}: ${errorText}`);
                }

                const result = await response.json();

                if (result.success) {
                    alert(`✅ Person tagged successfully!\n${result.message}`);
                    closeTagPersonModal();
                } else {
                    alert('Failed to tag person: ' + (result.message || 'Unknown error'));
                }
            } catch (error) {
                console.error('Tag person error:', error);
                alert('Failed to tag person: ' + error.message);
            }
        }

        // Event listeners
        console.log('Setting up event listeners...');
        const startBtn = document.getElementById('start-btn');
        console.log('Start button element:', startBtn);

        if (startBtn) {
            startBtn.addEventListener('click', () => {
                console.log('Start button clicked!');
                startCamera();
            });
            console.log('Start button listener attached');
        } else {
            console.error('Start button not found!');
        }

        document.getElementById('pause-btn').addEventListener('click', () => {
            isPaused = !isPaused;
            const btn = document.getElementById('pause-btn');
            btn.textContent = isPaused ? '▶️ Resume' : '⏸ Pause';
        });

        document.getElementById('red-flag-btn').addEventListener('click', openRedFlagModal);
        document.getElementById('tag-person-btn').addEventListener('click', openTagPersonModal);

        console.log('All event listeners set up');

        // === ALERT SYSTEM ===
        const alerts = [];
        let alertHistoryOpen = false;
        let bannerVisible = false;

        // Create alert sound using Web Audio API
        let audioCtx = null;
        function playAlertSound(level) {
            try {
                if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
                const osc = audioCtx.createOscillator();
                const gain = audioCtx.createGain();
                osc.connect(gain);
                gain.connect(audioCtx.destination);
                osc.type = 'square';

                if (level === 'critical') {
                    // Urgent double beep
                    osc.frequency.value = 880;
                    gain.gain.value = 0.3;
                    osc.start();
                    gain.gain.setValueAtTime(0.3, audioCtx.currentTime);
                    gain.gain.setValueAtTime(0, audioCtx.currentTime + 0.15);
                    gain.gain.setValueAtTime(0.3, audioCtx.currentTime + 0.25);
                    gain.gain.setValueAtTime(0, audioCtx.currentTime + 0.4);
                    osc.stop(audioCtx.currentTime + 0.5);
                } else {
                    // Single warning beep
                    osc.frequency.value = 660;
                    gain.gain.value = 0.2;
                    osc.start();
                    gain.gain.setValueAtTime(0, audioCtx.currentTime + 0.2);
                    osc.stop(audioCtx.currentTime + 0.3);
                }
            } catch (e) {
                console.warn('Audio alert failed:', e);
            }
        }

        function showAlertBanner(level, message) {
            const banner = document.getElementById('alert-banner');
            const text = document.getElementById('alert-banner-text');
            const icon = level === 'critical' ? '🚨' : '🔴';
            text.textContent = `${icon} ${message}`;
            banner.style.background = level === 'critical' ? '#dc2626' : '#ef4444';
            banner.style.display = 'block';
            bannerVisible = true;
        }

        function dismissBanner() {
            document.getElementById('alert-banner').style.display = 'none';
            bannerVisible = false;
        }

        function addAlert(level, message, timestamp) {
            const alert = { level, message, timestamp, id: Date.now() };
            alerts.unshift(alert);
            if (alerts.length > 50) alerts.pop();

            // Update badge
            const badge = document.getElementById('alert-badge');
            badge.textContent = alerts.length;
            badge.style.display = 'block';

            // Update history list if open
            renderAlertHistory();

            // Show banner and play sound
            showAlertBanner(level, message);
            playAlertSound(level);
        }

        function renderAlertHistory() {
            const list = document.getElementById('alert-list');
            if (alerts.length === 0) {
                list.innerHTML = '<p style="color:#666; font-size:13px;">No alerts yet</p>';
                return;
            }
            list.innerHTML = alerts.slice(0, 20).map(a => {
                const time = new Date(a.timestamp).toLocaleTimeString();
                const sevClass = a.level === 'critical' ? 'severity-critical' : 'severity-high';
                const icon = a.level === 'critical' ? '🚨' : '🔴';
                return `<div class="alert-item ${sevClass}">
                    <div class="alert-time">${icon} ${time}</div>
                    <div class="alert-desc">${a.message}</div>
                </div>`;
            }).join('');
        }

        function toggleAlertHistory() {
            const panel = document.getElementById('alert-history');
            alertHistoryOpen = !alertHistoryOpen;
            panel.style.display = alertHistoryOpen ? 'block' : 'none';
            if (alertHistoryOpen) renderAlertHistory();
        }

        // Plate display logic
        function updatePlateDisplay(plates) {
            const container = document.getElementById('plate-display');
            const box = document.getElementById('plate-box');
            const list = document.getElementById('plate-list');
            const header = document.getElementById('plate-header');

            if (!plates || !plates.detected || plates.detected.length === 0) {
                container.style.display = 'none';
                return;
            }

            container.style.display = 'block';
            const hasHotlist = plates.detected.some(p => p.hotlist_match);
            box.className = hasHotlist ? 'plate-box hotlist-match' : 'plate-box';
            header.textContent = hasHotlist ? 'HOTLIST PLATE DETECTED' : `License Plate${plates.count > 1 ? 's' : ''} Detected`;

            list.innerHTML = plates.detected.map(p => {
                let html = `<div class="plate-item">
                    <span class="plate-text">${p.display || p.text}</span>
                    <span class="plate-confidence">${Math.round(p.confidence * 100)}%</span>
                </div>`;
                if (p.hotlist_match) {
                    html += `<div class="plate-hotlist-warning">HOTLIST: ${p.hotlist_reason}</div>`;
                }
                if (p.impossible_travel && p.impossible_travel.alert) {
                    html += `<div class="plate-hotlist-warning">IMPOSSIBLE TRAVEL: ${p.impossible_travel.message}</div>`;
                }
                return html;
            }).join('');
        }

        // Hook into updateThreatDisplay to trigger alerts and plate display
        const _origUpdateThreat = updateThreatDisplay;
        updateThreatDisplay = function(result) {
            _origUpdateThreat(result);

            // Update plate display
            updatePlateDisplay(result.plates);

            // If alert was created by backend, add to local alert list
            if (result.alert_created && result.threat && (result.threat.level === 'warning' || result.threat.level === 'critical')) {
                const desc = result.ai_description ? result.ai_description.description : result.threat.message;
                addAlert(result.threat.level, `${result.threat.message} — ${desc}`, result.timestamp);
            }
        };

        // Load existing alerts on startup
        (async function loadExistingAlerts() {
            try {
                const resp = await fetch('/camera/alerts', {
                    headers: { 'Authorization': `Bearer ${token}` }
                });
                if (resp.ok) {
                    const existing = await resp.json();
                    existing.slice(0, 10).forEach(a => {
                        if (a.tags && a.tags.includes('auto_alert')) {
                            alerts.push({
                                level: a.severity === 'critical' ? 'critical' : 'warning',
                                message: a.description.replace('[AUTO] ', ''),
                                timestamp: a.timestamp,
                                id: Date.now() + Math.random()
                            });
                        }
                    });
                    if (alerts.length > 0) {
                        const badge = document.getElementById('alert-badge');
                        badge.textContent = alerts.length;
                        badge.style.display = 'block';
                        renderAlertHistory();
                    }
                }
            } catch (e) {
                console.warn('Failed to load existing alerts:', e);
            }
        })();
    </script>
</body>
</html>
"""
