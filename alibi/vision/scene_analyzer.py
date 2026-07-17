"""
Scene Analyzer - Natural Language Description of Camera Feeds

Uses vision AI to provide human-readable descriptions of what's actually in the frame.
"It's a cat" instead of "motion detected at coordinates..."
"""

import cv2
import numpy as np
import base64
import json
import re
import requests
from typing import Optional, Dict, Any, List
from datetime import datetime
import os


_VEHICLE_ATTR_INSTRUCTION = """

If one or more vehicles are visible, ALSO output — as the very last line, after
the description — exactly one JSON object of what you can actually see:
{"vehicles": [{"colour": "white", "make": "Toyota", "model": "Fortuner", "body": "SUV", "confidence": "high"}]}
Rules: "confidence" is high/medium/low for the make/model specifically. Use null
for any field you cannot honestly read from the image — never guess a make or
model from context; a wrong badge is worse than none. "body" is one of
sedan/hatchback/SUV/bakkie/van/minibus/truck/bus/motorcycle or null.
If no vehicle is visible, output no JSON at all."""


def parse_vehicle_attrs(text: str):
    """Split a VLM reply into (description, vehicles). Pure, so the honesty
    rules are testable: a field the model nulled — or filled with a placeholder
    like "unknown" — comes out as None (absent), never a default. Anything
    unparseable is simply no vehicles; the description always survives."""
    if not text:
        return "", []
    # Find the {"vehicles": ...} object wherever the model put it (it may be
    # followed by whitespace or wrapped in a code fence).
    decoder = json.JSONDecoder()
    raw, head = None, text
    for m in re.finditer(r"\{", text):
        try:
            data, end = decoder.raw_decode(text, m.start())
        except ValueError:
            continue
        if isinstance(data, dict) and isinstance(data.get("vehicles"), list):
            raw = data["vehicles"]
            head = (text[:m.start()] + text[end:]).replace("```json", "").replace("```", "")
            break
    if raw is None:
        return text.strip(), []

    def _s(v):
        v = str(v).strip() if v is not None else ""
        return v if v and v.lower() not in ("unknown", "n/a", "none", "null") else None

    vehicles = []
    for item in raw[:8]:
        if not isinstance(item, dict):
            continue
        conf = str(item.get("confidence") or "").lower()
        vehicles.append({
            "colour": _s(item.get("colour") or item.get("color")),
            "make": _s(item.get("make")),
            "model": _s(item.get("model")),
            "body": _s(item.get("body")),
            "confidence": conf if conf in ("high", "medium", "low") else "low",
        })
    return head.strip(), vehicles


class SceneAnalyzer:
    """
    Analyzes camera frames and provides natural language descriptions.
    
    Supports:
    - Local Ollama vision (data stays in-country — preferred)
    - Claude (Anthropic) Vision — preferred cloud model
    - OpenAI Vision API (optional fallback)
    - Google Cloud Vision (optional fallback)
    - Fallback to basic CV descriptions
    """

    def __init__(self, mode: str = "auto"):
        """
        Initialize scene analyzer.

        Args:
            mode: "claude", "openai", "google", "ollama", "local", or "auto"
                  (try in order). In auto mode, prefers local Ollama, then Claude,
                  for data sovereignty and quality.
        """
        self.mode = mode
        self.claude_available = False
        self.openai_available = False
        self.google_available = False
        self.ollama_available = False
        self.ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434")
        self.ollama_vision_model = os.getenv("OLLAMA_VISION_MODEL", "llama3.2-vision")
        self.anthropic_vision_model = os.getenv(
            "ANTHROPIC_VISION_MODEL", "claude-opus-4-8"
        )

        # Try Ollama (local, data never leaves the network)
        try:
            resp = requests.get(f"{self.ollama_url}/api/tags", timeout=2)
            if resp.status_code == 200:
                self.ollama_available = True
                print(f"[SceneAnalyzer] Ollama available at {self.ollama_url} (local AI — data stays in-country)")
        except Exception:
            pass

        # Try to import Anthropic (Claude) — preferred cloud model
        try:
            import anthropic
            self.anthropic_api_key = os.getenv('ANTHROPIC_API_KEY')
            if self.anthropic_api_key:
                self.anthropic_client = anthropic.Anthropic(api_key=self.anthropic_api_key)
                self.claude_available = True
                print("[SceneAnalyzer] Claude Vision available (cloud — data leaves network)")
        except ImportError:
            pass

        # Try to import OpenAI (optional fallback)
        try:
            import openai
            self.openai_api_key = os.getenv('OPENAI_API_KEY')
            if self.openai_api_key:
                self.openai_client = openai.OpenAI(api_key=self.openai_api_key)
                self.openai_available = True
                print("[SceneAnalyzer] OpenAI Vision API available (cloud — data leaves network)")
        except ImportError:
            pass

        # Try to import Google Vision
        try:
            from google.cloud import vision
            self.google_client = vision.ImageAnnotatorClient()
            self.google_available = True
            print("[SceneAnalyzer] Google Cloud Vision available (cloud — data leaves network)")
        except:
            pass

        if not (self.ollama_available or self.claude_available or self.openai_available or self.google_available):
            print("[SceneAnalyzer] Using basic computer vision (install Ollama for local AI, or set ANTHROPIC_API_KEY for Claude)")
    
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
            # Prefer local Ollama (data stays in-country); then Claude, the
            # preferred cloud model; then OpenAI/Google as optional fallbacks.
            if self.ollama_available:
                return self._analyze_with_ollama(frame, prompt)
            elif self.claude_available:
                return self._analyze_with_claude(frame, prompt)
            elif self.openai_available:
                return self._analyze_with_openai(frame, prompt)
            elif self.google_available:
                return self._analyze_with_google(frame, prompt)
            else:
                return self._analyze_with_basic_cv(frame, prompt)
        elif self.mode == "ollama":
            return self._analyze_with_ollama(frame, prompt)
        elif self.mode == "claude":
            return self._analyze_with_claude(frame, prompt)
        elif self.mode == "openai":
            return self._analyze_with_openai(frame, prompt)
        elif self.mode == "google":
            return self._analyze_with_google(frame, prompt)
        else:
            return self._analyze_with_basic_cv(frame, prompt)
    
    def _analyze_with_ollama(self, frame: np.ndarray, prompt: str) -> Dict[str, Any]:
        """Analyze using local Ollama vision model (data never leaves the network)."""
        try:
            # Encode frame to base64
            _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            base64_image = base64.b64encode(buffer).decode('utf-8')

            # Build prompt (the vehicles variant gets the same scene prompt here —
            # structured attrs are only extracted on the Claude path)
            if prompt in ("describe_scene", "describe_scene_vehicles"):
                system_prompt = (
                    "You are a security camera analyst. Describe this frame in 2-3 clear sentences. "
                    "For people: count, clothing, activities, position. For objects/scene: notable items, setting, safety concerns."
                )

                # Inject few-shot training examples for improved analysis
                try:
                    from alibi.training_selector import get_training_selector
                    training_context = get_training_selector().get_context_for_scene(system_prompt)
                    if training_context:
                        system_prompt += training_context
                except Exception:
                    pass  # Fall back to base prompt if selector fails

            elif prompt == "detect_activity":
                system_prompt = "Describe any human activity you see. If no humans, say 'No human activity detected'."
            elif prompt == "count_people":
                system_prompt = "Count the number of people visible. Format: 'X people visible' or 'No people visible'."
            else:
                system_prompt = "Describe what you see in this security camera frame."

            response = requests.post(
                f"{self.ollama_url}/api/chat",
                json={
                    "model": self.ollama_vision_model,
                    "messages": [
                        {
                            "role": "user",
                            "content": system_prompt,
                            "images": [base64_image],
                        }
                    ],
                    "stream": False,
                    "options": {"temperature": 0.3, "num_predict": 150},
                },
                timeout=30,
            )
            response.raise_for_status()
            result = response.json()
            description = result.get("message", {}).get("content", "").strip()

            if not description:
                return self._analyze_with_basic_cv(frame, prompt)

            # Extract safety concerns
            safety_keywords = ["fight", "weapon", "attack", "theft", "break", "suspicious", "danger", "emergency"]
            safety_concern = any(keyword in description.lower() for keyword in safety_keywords)

            common_objects = ["person", "car", "cat", "dog", "bike", "motorcycle", "truck", "door", "window"]
            detected_objects = [obj for obj in common_objects if obj in description.lower()]

            return {
                "description": description,
                "confidence": 0.80,
                "detected_objects": detected_objects,
                "detected_activities": self._extract_activities(description),
                "safety_concern": safety_concern,
                "method": "ollama_vision",
                "timestamp": datetime.utcnow().isoformat(),
            }

        except Exception as e:
            print(f"[SceneAnalyzer] Ollama error: {e}")
            # Fall back to OpenAI if available, then basic CV
            if self.openai_available:
                return self._analyze_with_openai(frame, prompt)
            return self._analyze_with_basic_cv(frame, prompt)

    def _scene_system_prompt(self, prompt: str) -> str:
        """Build the vision system prompt for a request type, including the
        South-African/Namibian regional context, any learned context, and
        few-shot training examples. Shared by the Claude and OpenAI paths."""
        if prompt == "detect_activity":
            return "Describe any human activity you see. If no humans, say 'No human activity detected'."
        if prompt == "count_people":
            return "Count the number of people visible. Format: 'X people visible' or 'No people visible'."
        if prompt not in ("describe_scene", "describe_scene_vehicles"):
            return "Describe what you see in this security camera frame."

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
        try:
            from alibi.continuous_learning import get_learning_system
            learned_context = get_learning_system().get_enhanced_prompt_context()
            if learned_context:
                system_prompt += f"\n\n{learned_context}"
        except Exception:
            pass  # Fall back to base prompt if learning system unavailable

        # Inject few-shot training examples for improved analysis
        try:
            from alibi.training_selector import get_training_selector
            training_context = get_training_selector().get_context_for_scene(system_prompt)
            if training_context:
                system_prompt += training_context
        except Exception:
            pass  # Fall back to base prompt if selector fails

        # Structured vehicle attributes ride the SAME call (the frame already
        # earned it) — the parse enforces "from the image or absent".
        if prompt == "describe_scene_vehicles":
            system_prompt += _VEHICLE_ATTR_INSTRUCTION

        return system_prompt

    def _analyze_with_claude(self, frame: np.ndarray, prompt: str) -> Dict[str, Any]:
        """Analyze using Claude (Anthropic) Vision — the preferred cloud model.

        Claude reads images natively via the Messages API. Sampling params
        (temperature) are omitted — the current Opus models reject them (400) —
        and no thinking is requested, since these are short real-time outputs.
        """
        try:
            # Encode frame to base64
            _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            base64_image = base64.b64encode(buffer).decode('utf-8')

            system_prompt = self._scene_system_prompt(prompt)

            # The owner can downgrade the vision model from the Costs page —
            # read per call so the change applies without a restart.
            try:
                from alibi.ai_config import get_ai_config
                vision_model = get_ai_config()["vision_model"]
            except Exception:
                vision_model = self.anthropic_vision_model

            response = self.anthropic_client.messages.create(
                model=vision_model,
                max_tokens=320 if prompt == "describe_scene_vehicles" else 150,
                system=system_prompt,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/jpeg",
                                    "data": base64_image,
                                },
                            },
                            {"type": "text", "text": "Describe this security camera frame."},
                        ],
                    }
                ],
            )

            description = "".join(
                block.text
                for block in response.content
                if getattr(block, "type", None) == "text"
            ).strip()

            try:
                from alibi.cost_tracker import record_from_response
                record_from_response("vision", vision_model, response)
            except Exception:
                pass

            if not description:
                return self._analyze_with_basic_cv(frame, prompt)

            # Structured vehicle attributes (when asked for): split the trailing
            # JSON off the prose. Fields the model couldn't read are absent.
            vehicles = []
            if prompt == "describe_scene_vehicles":
                description, vehicles = parse_vehicle_attrs(description)

            safety_keywords = ["fight", "weapon", "attack", "theft", "break", "suspicious", "danger", "emergency"]
            safety_concern = any(keyword in description.lower() for keyword in safety_keywords)

            common_objects = ["person", "car", "cat", "dog", "bike", "motorcycle", "truck", "door", "window"]
            detected_objects = [obj for obj in common_objects if obj in description.lower()]

            result = {
                "description": description,
                "confidence": 0.85,  # Claude doesn't provide a numeric confidence
                "detected_objects": detected_objects,
                "detected_activities": self._extract_activities(description),
                "safety_concern": safety_concern,
                "method": "claude_vision",
                "timestamp": datetime.utcnow().isoformat(),
            }
            if vehicles:
                result["vehicles"] = vehicles
            return result

        except Exception as e:
            print(f"[SceneAnalyzer] Claude error: {e}")
            # Fall back to OpenAI if available, then basic CV
            if self.openai_available:
                return self._analyze_with_openai(frame, prompt)
            return self._analyze_with_basic_cv(frame, prompt)

    def _analyze_with_openai(self, frame: np.ndarray, prompt: str) -> Dict[str, Any]:
        """Analyze using OpenAI Vision API (optional fallback)."""
        try:
            # Encode frame to base64
            _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            base64_image = base64.b64encode(buffer).decode('utf-8')

            system_prompt = self._scene_system_prompt(prompt)

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

            # Same structured-vehicles contract as the Claude path.
            vehicles = []
            if prompt == "describe_scene_vehicles":
                description, vehicles = parse_vehicle_attrs(description)

            # Extract safety concerns
            safety_keywords = ["fight", "weapon", "attack", "theft", "break", "suspicious", "danger", "emergency"]
            safety_concern = any(keyword in description.lower() for keyword in safety_keywords)

            # Extract objects (basic)
            common_objects = ["person", "car", "cat", "dog", "bike", "motorcycle", "truck", "door", "window"]
            detected_objects = [obj for obj in common_objects if obj in description.lower()]

            result = {
                "description": description,
                "confidence": 0.85,  # OpenAI doesn't provide confidence
                "detected_objects": detected_objects,
                "detected_activities": self._extract_activities(description),
                "safety_concern": safety_concern,
                "method": "openai_vision",
                "timestamp": datetime.utcnow().isoformat()
            }
            if vehicles:
                result["vehicles"] = vehicles
            return result
        
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
