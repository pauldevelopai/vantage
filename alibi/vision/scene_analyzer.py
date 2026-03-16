"""
Scene Analyzer - Natural Language Description of Camera Feeds

Uses vision AI to provide human-readable descriptions of what's actually in the frame.
"It's a cat" instead of "motion detected at coordinates..."
"""

import cv2
import numpy as np
import base64
import json
from typing import Optional, Dict, Any, List
from datetime import datetime
import os


class SceneAnalyzer:
    """
    Analyzes camera frames and provides natural language descriptions.
    
    Supports:
    - OpenAI Vision API (GPT-4 Vision)
    - Google Cloud Vision
    - Local BLIP/CLIP models
    - Fallback to basic CV descriptions
    """
    
    def __init__(self, mode: str = "auto"):
        """
        Initialize scene analyzer.
        
        Args:
            mode: "openai", "google", "local", or "auto" (try in order)
        """
        self.mode = mode
        self.openai_available = False
        self.google_available = False
        
        # Try to import OpenAI
        try:
            import openai
            self.openai_api_key = os.getenv('OPENAI_API_KEY')
            if self.openai_api_key:
                self.openai_client = openai.OpenAI(api_key=self.openai_api_key)
                self.openai_available = True
                print("[SceneAnalyzer] OpenAI Vision API available")
        except ImportError:
            pass
        
        # Try to import Google Vision
        try:
            from google.cloud import vision
            self.google_client = vision.ImageAnnotatorClient()
            self.google_available = True
            print("[SceneAnalyzer] Google Cloud Vision available")
        except:
            pass
        
        # Fallback to basic CV
        if not self.openai_available and not self.google_available:
            print("[SceneAnalyzer] Using basic computer vision (install OpenAI or Google Cloud for better results)")
    
    def analyze_frame(self, frame: np.ndarray, prompt: str = "describe_scene") -> Dict[str, Any]:
        """
        Analyze a frame and return natural language description.
        
        Args:
            frame: BGR image frame
            prompt: What to analyze ("describe_scene", "count_people", "detect_activity", etc.)
            
        Returns:
            {
                "description": "Two men fighting near a parked car",
                "confidence": 0.85,
                "detected_objects": ["person", "person", "car"],
                "detected_activities": ["fighting"],
                "safety_concern": True,
                "raw_response": {...}
            }
        """
        if self.mode == "auto":
            if self.openai_available:
                return self._analyze_with_openai(frame, prompt)
            elif self.google_available:
                return self._analyze_with_google(frame, prompt)
            else:
                return self._analyze_with_basic_cv(frame, prompt)
        elif self.mode == "openai":
            return self._analyze_with_openai(frame, prompt)
        elif self.mode == "google":
            return self._analyze_with_google(frame, prompt)
        else:
            return self._analyze_with_basic_cv(frame, prompt)
    
    def _analyze_with_openai(self, frame: np.ndarray, prompt: str) -> Dict[str, Any]:
        """Analyze using OpenAI Vision API with South African context"""
        try:
            # Import SA context and learning system
            from alibi.vision.south_african_context import enhance_prompt_for_sa_context
            from alibi.continuous_learning import get_learning_system

            # Get learned context
            learning_system = get_learning_system()
            learned_context = learning_system.get_enhanced_prompt_context()

            # Encode frame to base64
            _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            base64_image = base64.b64encode(buffer).decode('utf-8')
            
            # Construct prompt based on request type
            if prompt == "describe_scene":
                system_prompt = """You are a security camera analyst operating in South Africa and Namibia.

Regional Context:
- Common vehicles: Minibus taxis (Toyota Quantum), bakkies (pickup trucks)
- Locations: Townships, informal settlements, RDP houses, security estates
- Objects: Braai (BBQ), spaza shops, burglar bars, electric fences
- Activities: Queueing, street vendors, taxi ranks
- Wildlife (Namibia): Oryx, springbok, kudu, elephants
- Security: Electric fences, armed response, boom gates common

Cultural Sensitivity:
- Use respectful, factual language
- Describe what you see without judgment
- Use correct regional terminology

Describe this camera frame in 2-3 clear sentences.

For PEOPLE, always describe:
- How many people
- What they're wearing (colors, clothing type)
- What they're doing (walking, sitting, standing, working, etc.)
- Their approximate position in frame (foreground, background, left, right)
- Any interactions or activities

For OBJECTS and SCENE:
- Notable objects visible
- Location/setting if identifiable
- Any safety concerns or unusual activity

Examples:
- "One person in blue shirt and jeans standing in center of frame, appears to be looking at phone. Residential setting with burglar bars visible on windows in background."
- "Two people wearing work uniforms in foreground, appear to be having conversation. One holding clipboard. Industrial/commercial setting."
- "Three people sitting at table in outdoor area, appear to be eating/braaiing. Casual residential backyard setting."
- "Person in security guard uniform standing at boom gate, holding radio. Estate entrance visible."
- "Empty office space, no people visible. Desk and computer equipment present."

Be descriptive, factual, and include visual details about people."""

                # Add learned context if available
                if learned_context:
                    system_prompt += f"\n\n{learned_context}"

            elif prompt == "detect_activity":
                system_prompt = "Describe any human activity you see. If no humans, say 'No human activity detected'."
            elif prompt == "count_people":
                system_prompt = "Count the number of people visible. Format: 'X people visible' or 'No people visible'."
            else:
                system_prompt = "Describe what you see in this security camera frame."
            
            # Call OpenAI Vision API
            response = self.openai_client.chat.completions.create(
                model="gpt-4o-mini",  # Fast and cheap for real-time analysis
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": system_prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{base64_image}",
                                    "detail": "low"  # Faster, cheaper
                                }
                            }
                        ]
                    }
                ],
                max_tokens=150,
                temperature=0.3
            )
            
            description = response.choices[0].message.content.strip()
            
            # Extract safety concerns
            safety_keywords = ["fight", "weapon", "attack", "theft", "break", "suspicious", "danger", "emergency"]
            safety_concern = any(keyword in description.lower() for keyword in safety_keywords)
            
            # Extract objects (basic)
            common_objects = ["person", "car", "cat", "dog", "bike", "motorcycle", "truck", "door", "window"]
            detected_objects = [obj for obj in common_objects if obj in description.lower()]
            
            return {
                "description": description,
                "confidence": 0.85,  # OpenAI doesn't provide confidence
                "detected_objects": detected_objects,
                "detected_activities": self._extract_activities(description),
                "safety_concern": safety_concern,
                "method": "openai_vision",
                "timestamp": datetime.utcnow().isoformat()
            }
        
        except Exception as e:
            print(f"[SceneAnalyzer] OpenAI error: {e}")
            # Fallback to basic CV
            return self._analyze_with_basic_cv(frame, prompt)
    
    def _analyze_with_google(self, frame: np.ndarray, prompt: str) -> Dict[str, Any]:
        """Analyze using Google Cloud Vision"""
        try:
            from google.cloud import vision
            
            # Encode frame
            _, buffer = cv2.imencode('.jpg', frame)
            content = buffer.tobytes()
            
            image = vision.Image(content=content)
            
            # Perform label detection and object localization
            response = self.google_client.label_detection(image=image)
            labels = response.label_annotations
            
            # Object detection
            objects_response = self.google_client.object_localization(image=image)
            objects = objects_response.localized_object_annotations
            
            # Build description
            detected_objects = [obj.name.lower() for obj in objects]
            detected_labels = [label.description.lower() for label in labels[:5]]
            
            # Construct natural language description
            if not detected_objects:
                description = f"Scene contains: {', '.join(detected_labels[:3])}"
            else:
                description = f"Detected: {', '.join(detected_objects)}"
            
            return {
                "description": description,
                "confidence": labels[0].score if labels else 0.5,
                "detected_objects": detected_objects,
                "detected_activities": [],
                "safety_concern": False,
                "method": "google_vision",
                "timestamp": datetime.utcnow().isoformat()
            }
        
        except Exception as e:
            print(f"[SceneAnalyzer] Google Vision error: {e}")
            return self._analyze_with_basic_cv(frame, prompt)
    
    def _analyze_with_basic_cv(self, frame: np.ndarray, prompt: str) -> Dict[str, Any]:
        """Basic computer vision fallback"""
        
        # Convert to grayscale for analysis
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        
        # Detect motion/activity
        mean_intensity = np.mean(gray)
        std_intensity = np.std(gray)
        
        # Simple heuristics
        if std_intensity < 10:
            description = "Static scene, very low activity"
        elif std_intensity < 30:
            description = "Calm scene with minimal movement"
        elif std_intensity < 60:
            description = "Moderate activity detected"
        else:
            description = "High activity or complex scene detected"
        
        # Try basic face detection
        try:
            face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
            faces = face_cascade.detectMultiScale(gray, 1.1, 4)
            
            if len(faces) > 0:
                description = f"{len(faces)} person(s) detected in frame"
        except:
            pass
        
        return {
            "description": description,
            "confidence": 0.5,
            "detected_objects": [],
            "detected_activities": [],
            "safety_concern": False,
            "method": "basic_cv",
            "timestamp": datetime.utcnow().isoformat()
        }
    
    def _extract_activities(self, description: str) -> List[str]:
        """Extract activities from description"""
        activities = []
        activity_keywords = {
            "fighting": ["fight", "fighting", "punch", "kick", "attack"],
            "running": ["run", "running", "sprint"],
            "walking": ["walk", "walking"],
            "sitting": ["sit", "sitting", "seated"],
            "standing": ["stand", "standing"],
            "talking": ["talk", "talking", "conversation"],
            "arguing": ["argu", "dispute", "confrontation"]
        }
        
        desc_lower = description.lower()
        for activity, keywords in activity_keywords.items():
            if any(kw in desc_lower for kw in keywords):
                activities.append(activity)
        
        return activities
    
    def quick_describe(self, frame: np.ndarray) -> str:
        """
        Quick one-line description of the frame.
        
        Returns just the description string for simple use.
        """
        result = self.analyze_frame(frame, prompt="describe_scene")
        return result["description"]
