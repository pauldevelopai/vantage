"""
Vantage Event Simulator

Generates realistic camera events for demonstration and testing.
"""

import random
import hashlib
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from enum import Enum
from dataclasses import dataclass


class Scenario(str, Enum):
    """Predefined simulation scenarios"""
    QUIET_SHIFT = "quiet_shift"
    NORMAL_DAY = "normal_day"
    BUSY_EVENING = "busy_evening"
    SECURITY_INCIDENT = "security_incident"
    MIXED_EVENTS = "mixed_events"


@dataclass
class SimulatorConfig:
    """Configuration for event simulator"""
    scenario: Scenario
    rate_per_min: float
    seed: Optional[int] = None


class EventSimulator:
    """
    Generates realistic camera events for demos.
    
    Event types:
    - loitering
    - perimeter_breach (after-hours)
    - crowd_anomaly (people_count spike)
    - aggression_proxy (rapid_motion + clustering)
    - vehicle_stop_restricted
    """
    
    # Camera configurations
    CAMERAS = [
        {"id": "cam_entrance_main", "zone": "zone_entrance", "location": "Main Entrance"},
        {"id": "cam_lobby_west", "zone": "zone_lobby", "location": "West Lobby"},
        {"id": "cam_lobby_east", "zone": "zone_lobby", "location": "East Lobby"},
        {"id": "cam_parking_north", "zone": "zone_parking_north", "location": "North Parking"},
        {"id": "cam_parking_south", "zone": "zone_parking_south", "location": "South Parking"},
        {"id": "cam_perimeter_east", "zone": "zone_perimeter_east", "location": "East Perimeter"},
        {"id": "cam_perimeter_west", "zone": "zone_perimeter_west", "location": "West Perimeter"},
        {"id": "cam_restricted_area", "zone": "zone_restricted", "location": "Restricted Area"},
    ]
    
    def __init__(self, config: SimulatorConfig):
        self.config = config
        self.event_counter = 0
        self.start_time = datetime.utcnow()
        
        # Create dedicated Random instance for this simulator
        if config.seed is not None:
            self.rng = random.Random(config.seed)
        else:
            self.rng = random.Random()
        
        # Scenario configurations
        self.scenario_weights = self._get_scenario_weights(config.scenario)
    
    def _get_scenario_weights(self, scenario: Scenario) -> Dict[str, float]:
        """Get event type weights for scenario"""
        weights = {
            Scenario.QUIET_SHIFT: {
                "person_detected": 0.6,
                "vehicle_detected": 0.3,
                "loitering": 0.08,
                "perimeter_breach": 0.01,
                "crowd_anomaly": 0.0,
                "aggression_proxy": 0.01,
                "vehicle_stop_restricted": 0.0,
            },
            Scenario.NORMAL_DAY: {
                "person_detected": 0.5,
                "vehicle_detected": 0.25,
                "loitering": 0.15,
                "perimeter_breach": 0.02,
                "crowd_anomaly": 0.03,
                "aggression_proxy": 0.03,
                "vehicle_stop_restricted": 0.02,
            },
            Scenario.BUSY_EVENING: {
                "person_detected": 0.4,
                "vehicle_detected": 0.2,
                "loitering": 0.2,
                "perimeter_breach": 0.05,
                "crowd_anomaly": 0.1,
                "aggression_proxy": 0.03,
                "vehicle_stop_restricted": 0.02,
            },
            Scenario.SECURITY_INCIDENT: {
                "person_detected": 0.2,
                "vehicle_detected": 0.1,
                "loitering": 0.1,
                "perimeter_breach": 0.3,
                "crowd_anomaly": 0.05,
                "aggression_proxy": 0.2,
                "vehicle_stop_restricted": 0.05,
            },
            Scenario.MIXED_EVENTS: {
                "person_detected": 0.3,
                "vehicle_detected": 0.15,
                "loitering": 0.15,
                "perimeter_breach": 0.1,
                "crowd_anomaly": 0.1,
                "aggression_proxy": 0.1,
                "vehicle_stop_restricted": 0.1,
            },
        }
        
        return weights.get(scenario, weights[Scenario.NORMAL_DAY])
    
    def generate_event(self) -> Dict[str, Any]:
        """
        Generate a single camera event.
        
        Returns schema-valid CameraEvent dict.
        """
        self.event_counter += 1
        
        # Select event type based on scenario weights
        event_type = self.rng.choices(
            list(self.scenario_weights.keys()),
            weights=list(self.scenario_weights.values())
        )[0]
        
        # Select camera
        camera = self.rng.choice(self.CAMERAS)
        
        # Generate event ID
        timestamp = datetime.utcnow()
        event_id = self._generate_event_id(camera["id"], timestamp)
        
        # Base event
        event = {
            "event_id": event_id,
            "camera_id": camera["id"],
            "ts": timestamp.isoformat(),
            "zone_id": camera["zone"],
            "event_type": event_type,
            "confidence": 0.0,
            "severity": 1,
            "clip_url": None,
            "snapshot_url": None,
            "metadata": {},
        }
        
        # Generate type-specific details
        if event_type == "person_detected":
            event.update(self._generate_person_detected())
        elif event_type == "vehicle_detected":
            event.update(self._generate_vehicle_detected())
        elif event_type == "loitering":
            event.update(self._generate_loitering())
        elif event_type == "perimeter_breach":
            event.update(self._generate_perimeter_breach(camera))
        elif event_type == "crowd_anomaly":
            event.update(self._generate_crowd_anomaly())
        elif event_type == "aggression_proxy":
            event.update(self._generate_aggression_proxy())
        elif event_type == "vehicle_stop_restricted":
            event.update(self._generate_vehicle_stop_restricted(camera))
        
        # Add synthetic evidence URLs
        event["clip_url"] = f"https://storage.example.com/clips/{event_id}.mp4"
        event["snapshot_url"] = f"https://storage.example.com/snapshots/{event_id}.jpg"
        
        return event
    
    def _generate_event_id(self, camera_id: str, timestamp: datetime) -> str:
        """Generate deterministic event ID"""
        base = f"{camera_id}_{timestamp.isoformat()}_{self.event_counter}"
        hash_suffix = hashlib.md5(base.encode()).hexdigest()[:8]
        return f"sim_{self.event_counter:06d}_{hash_suffix}"
    
    def _generate_person_detected(self) -> Dict[str, Any]:
        """Generate person_detected event details"""
        return {
            "confidence": self.rng.uniform(0.75, 0.95),
            "severity": self.rng.choice([1, 2, 2, 3]),
            "metadata": {
                "person_count": 1,
                "direction": self.rng.choice(["entering", "exiting", "standing"]),
            }
        }
    
    def _generate_vehicle_detected(self) -> Dict[str, Any]:
        """Generate vehicle_detected event details"""
        return {
            "confidence": self.rng.uniform(0.80, 0.95),
            "severity": self.rng.choice([1, 2]),
            "metadata": {
                "vehicle_type": self.rng.choice(["car", "truck", "motorcycle"]),
                "speed_estimate": self.rng.choice(["slow", "normal", "fast"]),
            }
        }
    
    def _generate_loitering(self) -> Dict[str, Any]:
        """Generate loitering event details"""
        duration = self.rng.randint(120, 600)  # 2-10 minutes
        return {
            "confidence": self.rng.uniform(0.70, 0.88),
            "severity": self.rng.choice([2, 3, 3]),
            "metadata": {
                "duration_seconds": duration,
                "person_count": self.rng.choice([1, 1, 1, 2]),
                "behavior": "stationary",
            }
        }
    
    def _generate_perimeter_breach(self, camera: Dict[str, str]) -> Dict[str, Any]:
        """Generate perimeter_breach event details (after-hours)"""
        # Only generate at perimeter cameras
        if "perimeter" not in camera["zone"]:
            # Fallback to person_detected if not perimeter camera
            return self._generate_person_detected()
        
        return {
            "confidence": self.rng.uniform(0.75, 0.92),
            "severity": self.rng.choice([3, 4, 4, 5]),
            "metadata": {
                "breach_type": self.rng.choice(["fence_crossing", "gate_entry", "unauthorized_access"]),
                "after_hours": True,
                "direction": "entering",
            }
        }
    
    def _generate_crowd_anomaly(self) -> Dict[str, Any]:
        """Generate crowd_anomaly event details (people_count spike)"""
        people_count = self.rng.randint(8, 25)
        return {
            "confidence": self.rng.uniform(0.65, 0.85),
            "severity": self.rng.choice([3, 3, 4]),
            "metadata": {
                "people_count": people_count,
                "density": "high",
                "anomaly_type": "crowd_spike",
                "baseline_count": self.rng.randint(2, 5),
            }
        }
    
    def _generate_aggression_proxy(self) -> Dict[str, Any]:
        """Generate aggression_proxy event details (rapid_motion + clustering)"""
        return {
            "confidence": self.rng.uniform(0.60, 0.82),
            "severity": self.rng.choice([3, 4, 4]),
            "metadata": {
                "motion_intensity": "high",
                "rapid_motion": True,
                "clustering": True,
                "person_count": self.rng.randint(2, 5),
                "behavior": self.rng.choice(["altercation", "confrontation", "rapid_movement"]),
            }
        }
    
    def _generate_vehicle_stop_restricted(self, camera: Dict[str, str]) -> Dict[str, Any]:
        """Generate vehicle_stop_restricted event details"""
        # Only generate at restricted areas or parking
        if "restricted" not in camera["zone"] and "parking" not in camera["zone"]:
            return self._generate_vehicle_detected()
        
        return {
            "confidence": self.rng.uniform(0.70, 0.90),
            "severity": self.rng.choice([3, 3, 4]),
            "metadata": {
                "vehicle_type": self.rng.choice(["car", "truck", "van"]),
                "stopped_duration_seconds": self.rng.randint(30, 300),
                "restricted_zone": True,
                "license_plate_visible": self.rng.choice([True, False]),
            }
        }
    
    def validate_event(self, event: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """
        Validate event conforms to schema.
        
        Returns: (is_valid, error_message)
        """
        required_fields = [
            "event_id", "camera_id", "ts", "zone_id", "event_type",
            "confidence", "severity"
        ]
        
        # Check required fields
        for field in required_fields:
            if field not in event:
                return False, f"Missing required field: {field}"
        
        # Validate types
        if not isinstance(event["event_id"], str):
            return False, "event_id must be string"
        if not isinstance(event["camera_id"], str):
            return False, "camera_id must be string"
        if not isinstance(event["zone_id"], str):
            return False, "zone_id must be string"
        if not isinstance(event["event_type"], str):
            return False, "event_type must be string"
        
        # Validate ranges
        if not 0.0 <= event["confidence"] <= 1.0:
            return False, f"confidence must be 0.0-1.0, got {event['confidence']}"
        if not 1 <= event["severity"] <= 5:
            return False, f"severity must be 1-5, got {event['severity']}"
        
        # Validate timestamp
        try:
            datetime.fromisoformat(event["ts"])
        except ValueError:
            return False, f"Invalid timestamp format: {event['ts']}"
        
        return True, None
    
    def get_stats(self) -> Dict[str, Any]:
        """Get simulator statistics"""
        elapsed = (datetime.utcnow() - self.start_time).total_seconds()
        
        return {
            "events_generated": self.event_counter,
            "elapsed_seconds": elapsed,
            "rate_actual": self.event_counter / elapsed if elapsed > 0 else 0,
            "rate_target": self.config.rate_per_min,
            "scenario": self.config.scenario.value,
            "seed": self.config.seed,
        }
