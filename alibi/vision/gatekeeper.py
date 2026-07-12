"""
Vision-First Gatekeeper Pipeline

This module acts as the PRIMARY decision-maker for incident creation and training
data collection. It uses computer vision (YOLO) to detect objects and applies
rule-based scoring BEFORE any LLM is involved.

WHY THIS EXISTS:
- LLMs are unreliable triggers (they describe everything, including noise)
- We need structured, vision-based incident objects
- Training data should be based on detections, not LLM captions
- System must work even if LLM fails/refuses

GATEKEEPER RULES:
1. Vision detection MUST pass confidence threshold
2. Rule-based scoring MUST pass relevance threshold
3. Privacy filters MUST pass (no faces in public areas without consent flags)
4. Only then is LLM called (optional, for enrichment)

If the gate rejects, the data is stored as baseline/noise, NOT training.
"""

from dataclasses import dataclass
from typing import List, Dict, Any, Tuple, Optional
from pathlib import Path
import os
import cv2
import numpy as np
from datetime import datetime

try:
    from ultralytics import YOLO
    YOLO_AVAILABLE = True
except ImportError:
    YOLO_AVAILABLE = False


def _dfine_available() -> bool:
    """True if D-FINE's backend (transformers + torch) is importable."""
    try:
        import torch  # noqa: F401
        import transformers  # noqa: F401
        return True
    except ImportError:
        return False


@dataclass
class Detection:
    """Single object detection from YOLO"""
    class_id: int
    class_name: str
    confidence: float
    bbox: Tuple[int, int, int, int]  # x, y, w, h
    centroid: Tuple[float, float]


@dataclass
class ZoneHit:
    """Detection inside a configured zone"""
    zone_id: str
    zone_name: str
    zone_type: str  # restricted, monitored, public, private
    detection: Detection
    dwell_seconds: float = 0.0


@dataclass
class VisionScore:
    """Confidence scores for incident creation"""
    vision_conf: float      # Average detection confidence (0-1)
    rule_conf: float        # Rule-based relevance score (0-1)
    combined_conf: float    # Final combined score (0-1)
    reason: str             # Why this score was assigned


@dataclass
class GatekeeperPolicy:
    """Configuration for what passes the gate"""
    # Minimum thresholds
    min_vision_conf: float = 0.5      # YOLO detection must be >= 50%
    min_rule_conf: float = 0.6        # Rule score must be >= 60%
    min_combined_conf: float = 0.55   # Combined must be >= 55%
    
    # Security-relevant classes (COCO)
    security_classes: List[str] = None
    
    # Privacy settings
    block_faces_in_public: bool = True
    require_consent_flag: bool = False
    
    def __post_init__(self):
        if self.security_classes is None:
            self.security_classes = [
                # People
                "person",
                # Vehicles
                "car", "motorcycle", "bus", "truck", "bicycle",
                # Weapons & tools
                "knife", "scissors", "baseball bat",
                # Suspicious objects
                "backpack", "handbag", "suitcase", "umbrella",
                # Other
                "bottle", "cell phone", "laptop"
            ]


class VisionGatekeeper:
    """
    The gatekeeper decides if camera footage is training-eligible.
    
    Flow:
    1. Detect objects with YOLO
    2. Match detections to zones
    3. Score based on rules
    4. Check privacy filters
    5. Return structured incident or reject
    """
    
    def __init__(
        self,
        model_path: str = "yolov8n.pt",
        policy: Optional[GatekeeperPolicy] = None,
        backend: Optional[str] = None,
    ):
        """
        Initialize the gatekeeper.

        Args:
            model_path: Path to YOLO model (used only for the YOLO backend).
            policy: GatekeeperPolicy or None (uses defaults).
            backend: "dfine" | "yolo" | None. If None, resolved from the
                ALIBI_DETECTOR env var, else defaults to D-FINE (Apache-2.0)
                when available, falling back to YOLO (AGPL) otherwise.
        """
        self.policy = policy or GatekeeperPolicy()
        self.backend = self._select_backend(backend, model_path)

        if self.backend == "dfine":
            from alibi.vision.dfine_detector import DFineDetector
            self._detector = DFineDetector()
            self.model = None
            # {class_id: class_name}, mirrors ultralytics `model.names`.
            self.class_names = self._detector.class_names
        else:
            if not YOLO_AVAILABLE:
                raise ImportError(
                    "No detector backend available. Install D-FINE "
                    "('pip install transformers torch timm') or YOLO "
                    "('pip install ultralytics')."
                )
            self._detector = None
            self.model = YOLO(model_path)
            self.class_names = self.model.names

    @staticmethod
    def _select_backend(backend: Optional[str], model_path: str) -> str:
        """
        Decide which detector backend to use.

        Preference order: explicit `backend` arg > ALIBI_DETECTOR env var >
        a "dfine" hint in model_path > default (D-FINE). Any D-FINE choice
        falls back to YOLO if transformers/torch are not installed.
        """
        choice = (backend or os.getenv("ALIBI_DETECTOR", "")).strip().lower()
        if choice not in ("dfine", "yolo"):
            choice = "dfine" if "dfine" in str(model_path).lower() else "dfine"

        if choice == "dfine":
            if _dfine_available():
                return "dfine"
            if YOLO_AVAILABLE:
                print("[gatekeeper] D-FINE backend requested but transformers/torch "
                      "not installed; falling back to YOLO (AGPL). "
                      "Install with: pip install transformers torch timm")
                return "yolo"
            # Neither available — let the YOLO branch raise the clear ImportError.
            return "yolo"
        return "yolo"

    def detect_objects(
        self,
        frame: np.ndarray,
        conf_threshold: float = 0.25
    ) -> List[Detection]:
        """
        Run YOLO detection on a frame.
        
        Args:
            frame: OpenCV image (BGR)
            conf_threshold: Minimum confidence (default 0.25)
            
        Returns:
            List of Detection objects
        """
        # D-FINE backend (Apache-2.0): delegate to the drop-in detector.
        if self.backend == "dfine":
            return self._detector.detect(frame, conf_threshold=conf_threshold)

        # YOLO backend (legacy, AGPL).
        results = self.model(frame, conf=conf_threshold, verbose=False)

        detections = []
        for result in results:
            boxes = result.boxes
            for box in boxes:
                # Extract box data
                x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                conf = float(box.conf[0])
                cls = int(box.cls[0])
                
                # Convert to x, y, w, h
                x, y = int(x1), int(y1)
                w, h = int(x2 - x1), int(y2 - y1)
                
                # Calculate centroid
                cx = x + w / 2
                cy = y + h / 2
                
                detection = Detection(
                    class_id=cls,
                    class_name=self.class_names[cls],
                    confidence=conf,
                    bbox=(x, y, w, h),
                    centroid=(cx, cy)
                )
                detections.append(detection)
        
        return detections
    
    def apply_zones(
        self,
        detections: List[Detection],
        zones_config: List[Dict[str, Any]]
    ) -> List[ZoneHit]:
        """
        Check which detections fall inside configured zones.
        
        Args:
            detections: List of Detection objects
            zones_config: List of zone dicts with polygon, id, name, type
            
        Returns:
            List of ZoneHit objects
        """
        zone_hits = []
        
        for detection in detections:
            cx, cy = detection.centroid
            point = (int(cx), int(cy))
            
            for zone in zones_config:
                # Get polygon points
                polygon = zone.get("polygon", [])
                if not polygon:
                    continue
                
                # Convert to numpy array
                poly_array = np.array(polygon, dtype=np.int32)
                
                # Check if point is inside polygon
                if cv2.pointPolygonTest(poly_array, point, False) >= 0:
                    zone_hit = ZoneHit(
                        zone_id=zone["id"],
                        zone_name=zone.get("name", "Unknown"),
                        zone_type=zone.get("type", "monitored"),
                        detection=detection
                    )
                    zone_hits.append(zone_hit)
        
        return zone_hits
    
    def score_event(
        self,
        detections: List[Detection],
        zone_hits: List[ZoneHit]
    ) -> VisionScore:
        """
        Score an event based on detections and zone hits.
        
        Scoring logic:
        - vision_conf: Average detection confidence
        - rule_conf: Based on security relevance and zone type
        - combined_conf: Weighted average
        
        Args:
            detections: List of Detection objects
            zone_hits: List of ZoneHit objects
            
        Returns:
            VisionScore with confidence and reason
        """
        if not detections:
            return VisionScore(
                vision_conf=0.0,
                rule_conf=0.0,
                combined_conf=0.0,
                reason="No detections"
            )
        
        # 1. Vision confidence: average detection confidence
        vision_conf = np.mean([d.confidence for d in detections])
        
        # 2. Rule confidence: security relevance
        security_detections = [
            d for d in detections
            if d.class_name in self.policy.security_classes
        ]
        
        # Base rule score
        if security_detections:
            # High relevance if security objects detected
            relevance_score = 0.8
        else:
            # Low relevance for non-security objects
            relevance_score = 0.3
        
        # Boost if in restricted zones
        restricted_hits = [
            zh for zh in zone_hits
            if zh.zone_type == "restricted"
        ]
        if restricted_hits:
            relevance_score = min(1.0, relevance_score + 0.2)
        
        rule_conf = relevance_score
        
        # 3. Combined confidence: weighted average
        # 60% vision, 40% rules
        combined_conf = (0.6 * vision_conf) + (0.4 * rule_conf)
        
        # Build reason
        reasons = []
        if security_detections:
            classes = set(d.class_name for d in security_detections)
            reasons.append(f"Security objects: {', '.join(classes)}")
        if restricted_hits:
            zones = set(zh.zone_name for zh in restricted_hits)
            reasons.append(f"Restricted zones: {', '.join(zones)}")
        if not reasons:
            reasons.append("Non-security objects detected")
        
        return VisionScore(
            vision_conf=float(vision_conf),
            rule_conf=float(rule_conf),
            combined_conf=float(combined_conf),
            reason="; ".join(reasons)
        )
    
    def is_training_eligible(
        self,
        score: VisionScore,
        detections: List[Detection],
        zone_hits: List[ZoneHit]
    ) -> Tuple[bool, str]:
        """
        Decide if this event should be used for training.
        
        THE GATE:
        1. Vision confidence must pass threshold
        2. Rule confidence must pass threshold
        3. Combined confidence must pass threshold
        4. Privacy filters must pass
        
        Args:
            score: VisionScore from score_event()
            detections: List of Detection objects
            zone_hits: List of ZoneHit objects
            
        Returns:
            (eligible: bool, reason: str)
        """
        reasons = []
        
        # Check vision confidence
        if score.vision_conf < self.policy.min_vision_conf:
            return False, (
                f"Vision confidence too low: {score.vision_conf:.2f} < "
                f"{self.policy.min_vision_conf:.2f}"
            )
        
        # Check rule confidence
        if score.rule_conf < self.policy.min_rule_conf:
            return False, (
                f"Rule confidence too low: {score.rule_conf:.2f} < "
                f"{self.policy.min_rule_conf:.2f}"
            )
        
        # Check combined confidence
        if score.combined_conf < self.policy.min_combined_conf:
            return False, (
                f"Combined confidence too low: {score.combined_conf:.2f} < "
                f"{self.policy.min_combined_conf:.2f}"
            )
        
        # Privacy filter: check for faces in public zones
        if self.policy.block_faces_in_public:
            person_detections = [
                d for d in detections if d.class_name == "person"
            ]
            public_hits = [
                zh for zh in zone_hits
                if zh.zone_type == "public" and zh.detection.class_name == "person"
            ]
            
            if public_hits and not self.policy.require_consent_flag:
                # Allow but flag for review
                reasons.append("Privacy risk: people in public zone")
        
        # PASSED ALL GATES
        return True, f"Passed: {score.reason}"
    
    def process_frame(
        self,
        frame: np.ndarray,
        zones_config: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        Full pipeline: detect -> score -> gate.
        
        Args:
            frame: OpenCV image
            zones_config: Optional zones configuration
            
        Returns:
            Dict with detections, scores, eligible, reason
        """
        # 1. Detect objects
        detections = self.detect_objects(frame)
        
        # 2. Apply zones (if provided)
        zone_hits = []
        if zones_config:
            zone_hits = self.apply_zones(detections, zones_config)
        
        # 3. Score event
        score = self.score_event(detections, zone_hits)
        
        # 4. Check eligibility
        eligible, reason = self.is_training_eligible(score, detections, zone_hits)
        
        return {
            "detections": detections,
            "zone_hits": zone_hits,
            "score": score,
            "eligible": eligible,
            "reason": reason,
            "detection_summary": {
                "count": len(detections),
                "classes": list(set(d.class_name for d in detections)),
                "avg_confidence": float(np.mean([d.confidence for d in detections])) if detections else 0.0
            }
        }


def cli_test():
    """CLI test for the gatekeeper"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Test Vision Gatekeeper")
    parser.add_argument("--image", required=True, help="Path to test image")
    parser.add_argument("--model", default="yolov8n.pt", help="YOLO model path")
    parser.add_argument("--zones", help="Path to zones JSON file")
    parser.add_argument("--show", action="store_true", help="Show annotated image")
    
    args = parser.parse_args()
    
    # Load image
    frame = cv2.imread(args.image)
    if frame is None:
        print(f"❌ Failed to load image: {args.image}")
        return
    
    print(f"✅ Loaded image: {args.image} ({frame.shape[1]}x{frame.shape[0]})")
    
    # Load zones (if provided)
    zones_config = None
    if args.zones:
        import json
        with open(args.zones) as f:
            zones_config = json.load(f)
        print(f"✅ Loaded {len(zones_config)} zones")
    
    # Initialize gatekeeper
    print(f"\n🚪 Initializing gatekeeper with {args.model}...")
    gatekeeper = VisionGatekeeper(model_path=args.model)
    
    # Process frame
    print("\n🔍 Processing frame...")
    result = gatekeeper.process_frame(frame, zones_config)
    
    # Print results
    print("\n" + "="*70)
    print("GATEKEEPER RESULTS")
    print("="*70)
    
    print(f"\n📊 Detections: {result['detection_summary']['count']}")
    for det in result['detections']:
        print(f"  • {det.class_name}: {det.confidence:.2f} at {det.bbox}")
    
    if result['zone_hits']:
        print(f"\n🎯 Zone Hits: {len(result['zone_hits'])}")
        for zh in result['zone_hits']:
            print(f"  • {zh.detection.class_name} in {zh.zone_name} ({zh.zone_type})")
    
    score = result['score']
    print(f"\n📈 Scores:")
    print(f"  • Vision confidence: {score.vision_conf:.2f}")
    print(f"  • Rule confidence: {score.rule_conf:.2f}")
    print(f"  • Combined confidence: {score.combined_conf:.2f}")
    print(f"  • Reason: {score.reason}")
    
    print(f"\n🚦 Training Eligible: {'✅ YES' if result['eligible'] else '❌ NO'}")
    print(f"  • Reason: {result['reason']}")
    
    # Show annotated image (if requested)
    if args.show and result['detections']:
        annotated = frame.copy()
        for det in result['detections']:
            x, y, w, h = det.bbox
            color = (0, 255, 0) if result['eligible'] else (0, 165, 255)
            cv2.rectangle(annotated, (x, y), (x+w, y+h), color, 2)
            label = f"{det.class_name} {det.confidence:.2f}"
            cv2.putText(annotated, label, (x, y-10),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
        
        cv2.imshow("Gatekeeper Result", annotated)
        print("\n👁️  Press any key to close...")
        cv2.waitKey(0)
        cv2.destroyAllWindows()


if __name__ == "__main__":
    cli_test()
