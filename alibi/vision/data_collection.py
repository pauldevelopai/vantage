"""
Data Collection & Ingestion System for Vantage Vision

Collects real-world usage data to improve AI vision for South African context.

Key Features:
- User feedback on AI descriptions
- Context-specific corrections
- South African scenarios, objects, activities
- Privacy-preserving data collection
- Ethical data handling
- Fine-tuning dataset preparation
"""

import json
import uuid
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict
import hashlib


@dataclass
class FeedbackRecord:
    """User feedback on AI vision analysis"""
    feedback_id: str
    analysis_id: str
    timestamp: str
    user: str
    user_role: str
    
    # Original AI analysis
    original_description: str
    original_confidence: float
    original_objects: List[str]
    original_activities: List[str]
    original_safety_concern: bool
    
    # User corrections/feedback
    corrected_description: Optional[str] = None
    corrected_objects: Optional[List[str]] = None
    corrected_activities: Optional[List[str]] = None
    corrected_safety_concern: Optional[bool] = None
    
    # Feedback metadata
    feedback_type: str = "correction"  # correction, confirmation, addition, context
    accuracy_rating: Optional[int] = None  # 1-5 stars
    missing_context: Optional[str] = None  # What AI missed
    south_african_context: Optional[str] = None  # SA-specific notes
    
    # Privacy
    snapshot_hash: Optional[str] = None  # Hash instead of storing image
    location_context: Optional[str] = None  # General area (not exact location)
    
    metadata: Dict[str, Any] = None


class VisionDataCollector:
    """
    Manages data collection for improving Vantage Vision.
    
    Focuses on:
    - South African context (townships, informal settlements, vehicles, etc.)
    - Namibian context (desert, wildlife, local architecture)
    - African languages and terminology
    - Regional objects, activities, clothing
    - Cultural context and norms
    """
    
    def __init__(self, 
                 feedback_file: str = "alibi/data/vision_feedback.jsonl",
                 training_data_dir: str = "alibi/data/training_data"):
        self.feedback_file = Path(feedback_file)
        self.feedback_file.parent.mkdir(parents=True, exist_ok=True)
        
        self.training_data_dir = Path(training_data_dir)
        self.training_data_dir.mkdir(parents=True, exist_ok=True)
        (self.training_data_dir / "images").mkdir(exist_ok=True)
        (self.training_data_dir / "annotations").mkdir(exist_ok=True)
        
        if not self.feedback_file.exists():
            self.feedback_file.touch()
    
    def collect_feedback(self, feedback: FeedbackRecord) -> None:
        """
        Collect user feedback on AI analysis.
        
        This is the primary data collection mechanism:
        - Users correct AI descriptions
        - Mark what AI missed
        - Add South African context
        - Rate accuracy
        """
        with open(self.feedback_file, 'a') as f:
            f.write(json.dumps(asdict(feedback)) + '\n')
    
    def get_feedback_stats(self, days: int = 30) -> Dict[str, Any]:
        """Get statistics on collected feedback"""
        cutoff = datetime.utcnow().timestamp() - (days * 24 * 60 * 60)
        
        total = 0
        corrections = 0
        confirmations = 0
        ratings = []
        sa_contexts = []
        
        with open(self.feedback_file, 'r') as f:
            for line in f:
                if line.strip():
                    data = json.loads(line)
                    record_time = datetime.fromisoformat(data['timestamp']).timestamp()
                    
                    if record_time >= cutoff:
                        total += 1
                        
                        if data.get('feedback_type') == 'correction':
                            corrections += 1
                        elif data.get('feedback_type') == 'confirmation':
                            confirmations += 1
                        
                        if data.get('accuracy_rating'):
                            ratings.append(data['accuracy_rating'])
                        
                        if data.get('south_african_context'):
                            sa_contexts.append(data['south_african_context'])
        
        return {
            'total_feedback': total,
            'corrections': corrections,
            'confirmations': confirmations,
            'avg_rating': sum(ratings) / len(ratings) if ratings else 0,
            'total_ratings': len(ratings),
            'sa_context_notes': len(sa_contexts),
            'improvement_rate': (corrections / total * 100) if total > 0 else 0
        }
    
    def prepare_fine_tuning_dataset(self, output_file: str = "alibi/data/fine_tuning_dataset.jsonl"):
        """
        Prepare dataset for OpenAI fine-tuning.
        
        Format for GPT-4 Vision fine-tuning:
        {
            "messages": [
                {
                    "role": "system",
                    "content": "You are a security camera analyst in South Africa..."
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Describe this scene"},
                        {"type": "image_url", "image_url": {"url": "..."}}
                    ]
                },
                {
                    "role": "assistant",
                    "content": "Corrected description from user feedback"
                }
            ]
        }
        """
        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        system_prompt = """You are an AI security camera analyst operating in South Africa and Namibia.

Key context you must understand:
- South African townships, informal settlements, and urban areas
- Common South African vehicles (Toyota Quantum minibus taxis, bakkies, etc.)
- Regional architecture and building styles
- African cultural context and norms
- Wildlife in Namibia and South Africa
- Desert and savanna environments
- Multilingual context (English, Afrikaans, local languages)
- Local clothing and fashion
- Regional activities and behaviors

Be accurate, culturally sensitive, and context-aware. Describe what you see clearly and factually."""

        training_examples = []
        
        with open(self.feedback_file, 'r') as f:
            for line in f:
                if line.strip():
                    data = json.loads(line)
                    
                    # Only use corrections with high-quality feedback
                    if (data.get('feedback_type') == 'correction' and 
                        data.get('corrected_description') and
                        data.get('accuracy_rating', 0) >= 3):
                        
                        example = {
                            "messages": [
                                {
                                    "role": "system",
                                    "content": system_prompt
                                },
                                {
                                    "role": "user",
                                    "content": "Describe this security camera scene in South Africa"
                                },
                                {
                                    "role": "assistant",
                                    "content": data['corrected_description']
                                }
                            ]
                        }
                        
                        training_examples.append(example)
        
        # Write training dataset
        with open(output_path, 'w') as f:
            for example in training_examples:
                f.write(json.dumps(example) + '\n')
        
        return {
            'output_file': str(output_path),
            'total_examples': len(training_examples),
            'ready_for_fine_tuning': len(training_examples) >= 10
        }
    
    def extract_south_african_vocabulary(self) -> Dict[str, List[str]]:
        """
        Extract South African-specific vocabulary from feedback.
        
        This helps identify terms that OpenAI's base model might miss.
        """
        vocabulary = {
            'objects': set(),
            'activities': set(),
            'locations': set(),
            'vehicles': set(),
            'context_phrases': set()
        }
        
        with open(self.feedback_file, 'r') as f:
            for line in f:
                if line.strip():
                    data = json.loads(line)
                    
                    # Extract from corrected objects
                    if data.get('corrected_objects'):
                        vocabulary['objects'].update(data['corrected_objects'])
                    
                    # Extract from corrected activities
                    if data.get('corrected_activities'):
                        vocabulary['activities'].update(data['corrected_activities'])
                    
                    # Extract from SA context notes
                    if data.get('south_african_context'):
                        vocabulary['context_phrases'].add(data['south_african_context'])
        
        return {
            'objects': list(vocabulary['objects']),
            'activities': list(vocabulary['activities']),
            'locations': list(vocabulary['locations']),
            'vehicles': list(vocabulary['vehicles']),
            'context_phrases': list(vocabulary['context_phrases']),
            'total_unique_terms': sum(len(v) for v in vocabulary.values())
        }
    
    def export_improvement_report(self) -> str:
        """
        Generate a report on how to improve Vantage Vision.
        
        Returns markdown report.
        """
        stats = self.get_feedback_stats()
        vocab = self.extract_south_african_vocabulary()
        
        report = f"""# Vantage Vision Improvement Report

**Generated:** {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}

## Summary

- **Total Feedback Collected:** {stats['total_feedback']}
- **User Corrections:** {stats['corrections']}
- **Confirmations (AI was right):** {stats['confirmations']}
- **Average Accuracy Rating:** {stats['avg_rating']:.2f}/5.0
- **Improvement Needed:** {stats['improvement_rate']:.1f}% of analyses needed correction

## South African Context

- **SA-Specific Context Notes:** {stats['sa_context_notes']}
- **Unique Regional Terms:** {vocab['total_unique_terms']}

### Common Regional Objects
{chr(10).join('- ' + obj for obj in vocab['objects'][:20])}

### Common Regional Activities
{chr(10).join('- ' + act for act in vocab['activities'][:20])}

### Context Phrases
{chr(10).join('- ' + phrase for phrase in vocab['context_phrases'][:10])}

## Recommendations

1. **Fine-Tuning Readiness**
   - Current training examples: {stats['total_feedback']}
   - Recommended minimum: 100 high-quality examples
   - Status: {'Ready' if stats['total_feedback'] >= 100 else 'Collecting more data'}

2. **Priority Areas for Improvement**
   - Add South African vehicle recognition (bakkies, minibus taxis)
   - Improve township/informal settlement recognition
   - Enhance cultural context understanding
   - Add regional wildlife detection (Namibia)

3. **Data Collection Progress**
   - Continue collecting user feedback
   - Focus on SA-specific scenarios
   - Encourage detailed corrections
   - Build vocabulary database

## Next Steps

1. Reach 100+ high-quality corrections
2. Prepare fine-tuning dataset
3. Submit to OpenAI for fine-tuning
4. Test fine-tuned model
5. Deploy improved model
"""
        
        return report


# Global collector instance
_collector = None

def get_vision_data_collector() -> VisionDataCollector:
    """Get global vision data collector instance"""
    global _collector
    if _collector is None:
        _collector = VisionDataCollector()
    return _collector
