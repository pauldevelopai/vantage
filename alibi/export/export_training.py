"""
Defensible Training Data Export

Exports ONLY human-confirmed incidents with full provenance and audit trail.

Output formats:
- JSONL for LLM fine-tuning (OpenAI format)
- COCO-style annotations for object detection
- Manifest with full provenance

NOTHING is exported without human confirmation.
"""

import json
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime
from collections import defaultdict

from alibi.schema.training import (
    TrainingIncident,
    TrainingDataStore,
    ReviewStatus
)
from alibi.privacy.redact import redact_image, check_privacy_risk


class TrainingDataExporter:
    """
    Exports training data with full provenance and audit trail.
    
    Key principles:
    1. ONLY confirmed incidents
    2. Privacy-safe (redacted if needed)
    3. Full provenance (who, what, when, why)
    4. Audit trail included
    """
    
    def __init__(
        self,
        store: TrainingDataStore,
        export_dir: str = "alibi/data/exports"
    ):
        """
        Initialize exporter.
        
        Args:
            store: TrainingDataStore instance
            export_dir: Output directory for exports
        """
        self.store = store
        self.export_dir = Path(export_dir)
        self.export_dir.mkdir(parents=True, exist_ok=True)
    
    def export_for_fine_tuning(
        self,
        output_path: Optional[str] = None,
        redact_privacy_risks: bool = True
    ) -> Dict[str, Any]:
        """
        Export training data in OpenAI fine-tuning format.
        
        Format:
        {
            "messages": [
                {"role": "system", "content": "You are a security camera analyst..."},
                {"role": "user", "content": [{"type": "image_url", "image_url": {...}}]},
                {"role": "assistant", "content": "...structured description..."}
            ],
            "metadata": {
                "incident_id": "...",
                "camera_id": "...",
                "timestamp": "...",
                "rule_triggers": [...],
                "review": {...}
            }
        }
        
        Args:
            output_path: Optional output path (default: exports/training_dataset.jsonl)
            redact_privacy_risks: Whether to redact faces in images
            
        Returns:
            Export summary dict
        """
        if output_path is None:
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            output_path = self.export_dir / f"training_dataset_{timestamp}.jsonl"
        else:
            output_path = Path(output_path)
        
        # Get fine-tune eligible incidents
        eligible_incidents = self.store.get_fine_tune_eligible()
        
        if not eligible_incidents:
            return {
                "success": False,
                "error": "No fine-tune eligible incidents found",
                "total_incidents": len(self.store.get_all()),
                "confirmed_incidents": len(self.store.get_by_status(ReviewStatus.CONFIRMED)),
                "eligible_incidents": 0
            }
        
        print(f"\n📦 Exporting {len(eligible_incidents)} fine-tune eligible incidents...")
        
        exported_count = 0
        skipped_privacy = 0
        skipped_no_evidence = 0
        
        with open(output_path, "w") as f:
            for incident in eligible_incidents:
                # Check evidence exists
                evidence_frames = incident.incident_data.get("evidence_frames", [])
                evidence_clip = incident.incident_data.get("evidence_clip")
                
                if not evidence_frames and not evidence_clip:
                    skipped_no_evidence += 1
                    continue
                
                # Handle privacy
                if redact_privacy_risks and incident.review.faces_detected:
                    if not incident.review.faces_redacted:
                        # Should have been redacted in review UI
                        print(f"⚠️  Skipping {incident.incident_id}: faces not redacted")
                        skipped_privacy += 1
                        continue
                
                # Build OpenAI format
                example = self._build_openai_example(incident)
                
                # Write to file
                f.write(json.dumps(example) + "\n")
                exported_count += 1
        
        print(f"✅ Exported {exported_count} examples to {output_path}")
        if skipped_privacy > 0:
            print(f"⚠️  Skipped {skipped_privacy} for privacy (faces not redacted)")
        if skipped_no_evidence > 0:
            print(f"⚠️  Skipped {skipped_no_evidence} for missing evidence")
        
        return {
            "success": True,
            "output_path": str(output_path),
            "exported_count": exported_count,
            "skipped_privacy": skipped_privacy,
            "skipped_no_evidence": skipped_no_evidence,
            "total_eligible": len(eligible_incidents)
        }
    
    def _build_openai_example(self, incident: TrainingIncident) -> Dict[str, Any]:
        """
        Build OpenAI fine-tuning example from incident.
        
        Args:
            incident: TrainingIncident to convert
            
        Returns:
            OpenAI format dict
        """
        # System prompt
        system_prompt = (
            "You are a security camera analyst. "
            "Analyze video footage and provide structured descriptions of events, "
            "focusing on security-relevant information. "
            "Be factual, objective, and precise. "
            "Include: what objects are present, what activities are occurring, "
            "spatial context (zones), temporal context (duration), "
            "and any security concerns."
        )
        
        # User message (would include image/video in practice)
        # For now, we include text description
        evidence_frames = incident.incident_data.get("evidence_frames", [])
        evidence_clip = incident.incident_data.get("evidence_clip")
        
        user_content = f"Analyze this security footage."
        if evidence_frames:
            user_content += f" Evidence: {len(evidence_frames)} frames."
        if evidence_clip:
            user_content += f" Video clip: {evidence_clip}"
        
        # Assistant response (structured description)
        detections = incident.incident_data.get("detections", {})
        reason = incident.incident_data.get("reason", "")
        duration = incident.incident_data.get("duration_seconds", 0)
        zone_presence = incident.incident_data.get("zone_presence", {})
        
        assistant_response = {
            "event_type": incident.incident_data.get("category", "unknown"),
            "objects_detected": detections.get("classes", []),
            "object_counts": detections.get("counts", {}),
            "confidence": detections.get("avg_confidence", 0.0),
            "security_relevant": detections.get("security_relevant", False),
            "description": reason,
            "duration_seconds": duration,
            "zones": zone_presence,
            "security_assessment": self._generate_security_assessment(incident)
        }
        
        return {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
                {"role": "assistant", "content": json.dumps(assistant_response)}
            ],
            "metadata": {
                "incident_id": incident.incident_id,
                "camera_id": incident.source_camera_id,
                "timestamp": incident.source_timestamp.isoformat() if incident.source_timestamp else None,
                "triggered_rules": incident.incident_data.get("triggered_rules", []),
                "review": incident.review.to_dict() if incident.review else None,
                "collection_method": incident.collection_method,
                "created_at": incident.created_at.isoformat()
            }
        }
    
    def _generate_security_assessment(self, incident: TrainingIncident) -> str:
        """Generate security assessment text"""
        triggered_rules = incident.incident_data.get("triggered_rules", [])
        
        if not triggered_rules:
            return "Normal activity detected."
        
        assessments = []
        for rule in triggered_rules:
            if "restricted_zone" in rule:
                assessments.append("Unauthorized access to restricted area detected.")
            elif "loitering" in rule:
                assessments.append("Loitering behavior detected.")
            elif "unattended" in rule:
                assessments.append("Unattended object detected.")
            elif "rapid_movement" in rule:
                assessments.append("Rapid movement detected.")
            elif "crowd" in rule:
                assessments.append("Crowd formation detected.")
        
        return " ".join(assessments) if assessments else "Security event detected."
    
    def export_coco_annotations(
        self,
        output_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Export in COCO format for object detection training.
        
        Args:
            output_path: Optional output path
            
        Returns:
            Export summary dict
        """
        if output_path is None:
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            output_path = self.export_dir / f"coco_annotations_{timestamp}.json"
        else:
            output_path = Path(output_path)
        
        eligible_incidents = self.store.get_fine_tune_eligible()
        
        # Build COCO format
        coco_data = {
            "info": {
                "description": "Vantage Security Training Dataset",
                "version": "1.0",
                "year": datetime.utcnow().year,
                "date_created": datetime.utcnow().isoformat()
            },
            "licenses": [],
            "images": [],
            "annotations": [],
            "categories": []
        }
        
        # Collect unique categories
        categories_set = set()
        for incident in eligible_incidents:
            classes = incident.incident_data.get("detections", {}).get("classes", [])
            categories_set.update(classes)
        
        # Add categories
        for i, cat in enumerate(sorted(categories_set), 1):
            coco_data["categories"].append({
                "id": i,
                "name": cat,
                "supercategory": "object"
            })
        
        category_name_to_id = {
            cat["name"]: cat["id"]
            for cat in coco_data["categories"]
        }
        
        # Add images and annotations
        image_id = 1
        annotation_id = 1
        
        for incident in eligible_incidents:
            evidence_frames = incident.incident_data.get("evidence_frames", [])
            
            for frame_path in evidence_frames:
                # Add image
                coco_data["images"].append({
                    "id": image_id,
                    "file_name": str(frame_path),
                    "width": 1280,  # Would need to read actual dimensions
                    "height": 720,
                    "incident_id": incident.incident_id
                })
                
                # Add annotations (if bbox data available)
                # For now, just mark presence of objects
                detections = incident.incident_data.get("detections", {})
                for class_name, count in detections.get("counts", {}).items():
                    if class_name in category_name_to_id:
                        coco_data["annotations"].append({
                            "id": annotation_id,
                            "image_id": image_id,
                            "category_id": category_name_to_id[class_name],
                            "bbox": [0, 0, 100, 100],  # Placeholder
                            "area": 10000,
                            "iscrowd": 0,
                            "incident_id": incident.incident_id
                        })
                        annotation_id += 1
                
                image_id += 1
        
        # Write to file
        with open(output_path, "w") as f:
            json.dump(coco_data, f, indent=2)
        
        print(f"✅ Exported COCO annotations to {output_path}")
        print(f"   Images: {len(coco_data['images'])}")
        print(f"   Annotations: {len(coco_data['annotations'])}")
        print(f"   Categories: {len(coco_data['categories'])}")
        
        return {
            "success": True,
            "output_path": str(output_path),
            "num_images": len(coco_data["images"]),
            "num_annotations": len(coco_data["annotations"]),
            "num_categories": len(coco_data["categories"])
        }
    
    def export_manifest(
        self,
        output_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Export manifest with full provenance and audit trail.
        
        Manifest includes:
        - Dataset statistics
        - Review statistics
        - Privacy handling summary
        - Rejection reasons breakdown
        - Full audit trail
        
        Args:
            output_path: Optional output path
            
        Returns:
            Manifest dict
        """
        if output_path is None:
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            output_path = self.export_dir / f"manifest_{timestamp}.json"
        else:
            output_path = Path(output_path)
        
        all_incidents = self.store.get_all()
        eligible_incidents = self.store.get_fine_tune_eligible()
        counts = self.store.get_counts_by_status()
        
        # Rejection reasons breakdown
        rejection_reasons = defaultdict(int)
        for incident in all_incidents:
            if incident.review and incident.review.reject_reason:
                rejection_reasons[incident.review.reject_reason.value] += 1
        
        # Privacy stats
        privacy_stats = {
            "total_with_faces": 0,
            "total_redacted": 0,
            "redaction_methods": defaultdict(int)
        }
        for incident in all_incidents:
            if incident.review and incident.review.faces_detected:
                privacy_stats["total_with_faces"] += 1
                if incident.review.faces_redacted:
                    privacy_stats["total_redacted"] += 1
                    method = incident.review.redaction_method or "unknown"
                    privacy_stats["redaction_methods"][method] += 1
        
        # Reviewer breakdown
        reviewers = defaultdict(lambda: {"confirmed": 0, "rejected": 0, "needs_review": 0})
        for incident in all_incidents:
            if incident.review:
                username = incident.review.reviewer_username or "unknown"
                status = incident.review.status.value
                if status in reviewers[username]:
                    reviewers[username][status] += 1
        
        manifest = {
            "export_info": {
                "generated_at": datetime.utcnow().isoformat(),
                "alibi_version": "1.0.0",
                "export_type": "training_dataset"
            },
            "dataset_statistics": {
                "total_incidents": len(all_incidents),
                "fine_tune_eligible": len(eligible_incidents),
                "pending_review": counts["pending_review"],
                "confirmed": counts["confirmed"],
                "rejected": counts["rejected"],
                "needs_review": counts["needs_review"]
            },
            "rejection_breakdown": dict(rejection_reasons),
            "privacy_handling": {
                "total_with_faces": privacy_stats["total_with_faces"],
                "total_redacted": privacy_stats["total_redacted"],
                "redaction_methods": dict(privacy_stats["redaction_methods"]),
                "privacy_policy": "All faces must be redacted before fine-tuning"
            },
            "reviewers": dict(reviewers),
            "quality_assurance": {
                "human_confirmation_required": True,
                "privacy_redaction_required": True,
                "evidence_required": True,
                "min_confidence": 0.5
            },
            "audit_trail": [
                incident.to_dict()
                for incident in eligible_incidents
            ]
        }
        
        # Write to file
        with open(output_path, "w") as f:
            json.dump(manifest, f, indent=2)
        
        print(f"✅ Exported manifest to {output_path}")
        print(f"   Total incidents: {manifest['dataset_statistics']['total_incidents']}")
        print(f"   Fine-tune eligible: {manifest['dataset_statistics']['fine_tune_eligible']}")
        print(f"   Confirmed: {manifest['dataset_statistics']['confirmed']}")
        print(f"   Rejected: {manifest['dataset_statistics']['rejected']}")
        
        return manifest
    
    def export_all(self) -> Dict[str, Any]:
        """
        Export everything: JSONL, COCO, and manifest.
        
        Returns:
            Combined export summary
        """
        print("\n" + "="*70)
        print("EXPORTING DEFENSIBLE TRAINING DATASET")
        print("="*70)
        
        # Export OpenAI format
        print("\n1. OpenAI Fine-Tuning Format...")
        openai_result = self.export_for_fine_tuning()
        
        # Export COCO format
        print("\n2. COCO Annotations...")
        coco_result = self.export_coco_annotations()
        
        # Export manifest
        print("\n3. Provenance Manifest...")
        manifest = self.export_manifest()
        
        print("\n" + "="*70)
        print("✅ EXPORT COMPLETE")
        print("="*70)
        
        return {
            "openai": openai_result,
            "coco": coco_result,
            "manifest": manifest
        }
