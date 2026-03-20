"""
Continuous Learning System

Learns from user feedback to improve threat detection and scene analysis over time.

Key Learning Sources:
1. Person tagging (good/bad) - Learns what authorized vs unauthorized people look like
2. Red flags - Learns what suspicious situations look like
3. Incident reports - Learns from actual security events
4. AI analysis corrections - When users disagree with AI assessments

The system builds a knowledge base that enhances future AI prompts and threat assessments.
"""

from dataclasses import dataclass, asdict
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from pathlib import Path
import json
from collections import defaultdict

from alibi.known_persons import get_known_persons_store
from alibi.intelligence_store import get_intelligence_store


@dataclass
class LearningEntry:
    """A single learning entry from user feedback"""
    entry_id: str
    timestamp: str
    source: str  # "person_tag", "red_flag", "incident", "correction"
    category: str  # "authorized_person", "threat", "normal_activity", etc.
    description: str
    confidence: float  # How confident we are in this learning (0.0-1.0)
    metadata: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ContinuousLearningSystem:
    """
    Continuous learning system that improves over time.

    Learns from:
    - Person tagging (who is authorized)
    - Red flags (what is suspicious)
    - Incident reports (what went wrong)
    - AI corrections (when AI was wrong)
    """

    def __init__(self, storage_path: str = "alibi/data/learning.jsonl"):
        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self.learning_entries: List[LearningEntry] = []
        self._load_learning_entries()

        # Aggregated knowledge
        self.authorized_person_patterns: List[str] = []
        self.threat_patterns: List[str] = []
        self.normal_activity_patterns: List[str] = []

        self._build_knowledge_base()

    def _load_learning_entries(self):
        """Load all learning entries from storage"""
        if not self.storage_path.exists():
            return

        with open(self.storage_path, 'r') as f:
            for line in f:
                if line.strip():
                    data = json.loads(line)
                    entry = LearningEntry(**data)
                    self.learning_entries.append(entry)

    def add_learning_entry(self, entry: LearningEntry):
        """Add a new learning entry"""
        self.learning_entries.append(entry)

        # Append to storage
        with open(self.storage_path, 'a') as f:
            f.write(json.dumps(entry.to_dict()) + '\n')

        # Rebuild knowledge base
        self._build_knowledge_base()

        print(f"✅ Learning entry added: {entry.category} ({entry.source})")

    def _build_knowledge_base(self):
        """Build aggregated knowledge from learning entries"""
        self.authorized_person_patterns = []
        self.threat_patterns = []
        self.normal_activity_patterns = []

        # Aggregate patterns from entries
        for entry in self.learning_entries:
            if entry.category == "authorized_person" and entry.confidence > 0.6:
                self.authorized_person_patterns.append(entry.description)
            elif entry.category in ["threat", "suspicious"] and entry.confidence > 0.6:
                self.threat_patterns.append(entry.description)
            elif entry.category == "normal_activity" and entry.confidence > 0.6:
                self.normal_activity_patterns.append(entry.description)

    def learn_from_person_tag(self, person_name: str, person_role: str,
                              description: str, trust_level: str):
        """Learn from user tagging a person"""
        import uuid

        if trust_level == "trusted":
            category = "authorized_person"
            learning_description = f"Person '{person_name}' ({person_role}): {description} - AUTHORIZED"
        elif trust_level == "watch":
            category = "threat"
            learning_description = f"Person '{person_name}' ({person_role}): {description} - WATCH/UNAUTHORIZED"
        else:
            category = "neutral_person"
            learning_description = f"Person '{person_name}' ({person_role}): {description} - NEUTRAL"

        entry = LearningEntry(
            entry_id=str(uuid.uuid4()),
            timestamp=datetime.utcnow().isoformat(),
            source="person_tag",
            category=category,
            description=learning_description,
            confidence=0.8,  # User tagging is fairly reliable
            metadata={
                "person_name": person_name,
                "person_role": person_role,
                "trust_level": trust_level,
                "physical_description": description
            }
        )

        self.add_learning_entry(entry)

    def learn_from_red_flag(self, category: str, description: str, severity: str):
        """Learn from user creating a red flag"""
        import uuid

        learning_category = "threat" if severity in ["high", "critical"] else "suspicious"

        entry = LearningEntry(
            entry_id=str(uuid.uuid4()),
            timestamp=datetime.utcnow().isoformat(),
            source="red_flag",
            category=learning_category,
            description=f"Red flag ({category}, {severity}): {description}",
            confidence=0.7,  # Red flags are user-reported, fairly reliable
            metadata={
                "red_flag_category": category,
                "severity": severity,
                "description": description
            }
        )

        self.add_learning_entry(entry)

    def get_enhanced_prompt_context(self) -> str:
        """
        Generate enhanced prompt context based on learned patterns.

        This is added to the SceneAnalyzer prompt to incorporate learning.
        """
        context_parts = []

        # Add known person patterns
        persons_store = get_known_persons_store()
        authorized_persons = persons_store.get_authorized_persons()

        if authorized_persons:
            context_parts.append("\nKnown Authorized Persons:")
            for person in authorized_persons[:5]:  # Limit to 5 most recent
                context_parts.append(f"- {person.name} ({person.role}): {person.description}")

        # Add learned threat patterns
        if self.threat_patterns:
            context_parts.append("\nKnown Threat Patterns (from previous incidents):")
            for pattern in self.threat_patterns[-5:]:  # Last 5 patterns
                context_parts.append(f"- {pattern}")

        return "\n".join(context_parts) if context_parts else ""

    def get_threat_assessment_enhancement(self, ai_description: str) -> Dict[str, Any]:
        """
        Enhance threat assessment based on learned patterns.

        Returns additional threat intelligence based on what the system has learned.
        """
        enhancement = {
            "learned_patterns_matched": [],
            "known_persons_detected": [],
            "confidence_adjustment": 0.0
        }

        # Check if description matches any authorized person patterns
        persons_store = get_known_persons_store()
        all_persons = persons_store.get_all_persons()

        for person in all_persons:
            # Simple keyword matching (in production, use more sophisticated matching)
            if any(word.lower() in ai_description.lower()
                   for word in person.description.split()[:3]):  # First 3 words
                enhancement["known_persons_detected"].append({
                    "name": person.name,
                    "role": person.role,
                    "trust_level": person.trust_level,
                    "is_authorized": person.is_authorized
                })

        # Check if description matches threat patterns
        for pattern in self.threat_patterns:
            # Simple substring matching
            if any(word in ai_description.lower()
                   for word in pattern.lower().split()[:5]):  # Key words
                enhancement["learned_patterns_matched"].append({
                    "pattern": pattern,
                    "type": "threat"
                })

        return enhancement

    def get_statistics(self) -> Dict[str, Any]:
        """Get learning statistics"""
        stats = {
            "total_entries": len(self.learning_entries),
            "entries_by_source": defaultdict(int),
            "entries_by_category": defaultdict(int),
            "recent_entries": []
        }

        for entry in self.learning_entries:
            stats["entries_by_source"][entry.source] += 1
            stats["entries_by_category"][entry.category] += 1

        # Get recent entries (last 10)
        recent = sorted(self.learning_entries, key=lambda e: e.timestamp, reverse=True)[:10]
        stats["recent_entries"] = [e.to_dict() for e in recent]

        return stats


# Global instance
_learning_system: Optional[ContinuousLearningSystem] = None


def get_learning_system() -> ContinuousLearningSystem:
    """Get the global learning system instance"""
    global _learning_system
    if _learning_system is None:
        _learning_system = ContinuousLearningSystem()
    return _learning_system
