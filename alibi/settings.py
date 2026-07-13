"""
Vantage Settings Manager

Load and manage settings from alibi_settings.json
"""

import json
from pathlib import Path
from typing import Dict, Any, Optional


class VantageSettings:
    """Settings manager for Vantage"""
    
    def __init__(self, settings_file: str = "alibi/data/alibi_settings.json"):
        self.settings_file = Path(settings_file)
        self._settings = self._load_settings()
    
    def _load_settings(self) -> Dict[str, Any]:
        """Load settings from JSON file"""
        if not self.settings_file.exists():
            # Return defaults
            return self._get_defaults()
        
        try:
            with open(self.settings_file, "r") as f:
                return json.load(f)
        except Exception as e:
            print(f"Warning: Failed to load settings from {self.settings_file}: {e}")
            return self._get_defaults()
    
    def _get_defaults(self) -> Dict[str, Any]:
        """Get default settings"""
        return {
            "incident_grouping": {
                "merge_window_seconds": 300,
                "dedup_window_seconds": 30,
                "compatible_event_types": {
                    "loitering": ["loitering", "suspicious_behavior"],
                    "breach": ["breach", "unauthorized_access", "forced_entry"],
                    "person_detected": ["person_detected", "person_loitering"],
                    "vehicle_detected": ["vehicle_detected", "vehicle_loitering"]
                }
            },
            "thresholds": {
                "min_confidence_for_notify": 0.75,
                "min_confidence_for_action": 0.80,
                "high_severity_threshold": 4
            },
            "encryption": {
                "enabled": True
            },
            "llm": {
                "enabled": True,
                "provider": "auto",
                "model": "gpt-4o-mini",
                "max_tokens": 500,
                "temperature": 0.3,
                "ollama_url": "http://localhost:11434",
                "ollama_vision_model": "llama3.2-vision",
                "ollama_text_model": "llama3.2"
            },
            "api": {
                "port": 8000,
                "host": "0.0.0.0"
            }
        }
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get setting by key (supports dot notation)"""
        keys = key.split(".")
        value = self._settings
        
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
                if value is None:
                    return default
            else:
                return default
        
        return value
    
    @property
    def merge_window_seconds(self) -> int:
        """Get merge window in seconds"""
        return self.get("incident_grouping.merge_window_seconds", 300)
    
    @property
    def dedup_window_seconds(self) -> int:
        """Get dedup window in seconds"""
        return self.get("incident_grouping.dedup_window_seconds", 30)
    
    @property
    def min_confidence_for_notify(self) -> float:
        """Get minimum confidence for notify threshold"""
        return self.get("thresholds.min_confidence_for_notify", 0.75)
    
    @property
    def high_severity_threshold(self) -> int:
        """Get high severity threshold"""
        return self.get("thresholds.high_severity_threshold", 4)
    
    @property
    def api_port(self) -> int:
        """Get API port"""
        return self.get("api.port", 8000)
    
    @property
    def api_host(self) -> str:
        """Get API host"""
        return self.get("api.host", "0.0.0.0")
    
    def are_event_types_compatible(self, type1: str, type2: str) -> bool:
        """Check if two event types are compatible for grouping"""
        compatible_groups = self.get("incident_grouping.compatible_event_types", {})
        
        # Same type is always compatible
        if type1 == type2:
            return True
        
        # Check if they're in the same compatibility group
        for group_key, group_types in compatible_groups.items():
            if type1 in group_types and type2 in group_types:
                return True
        
        return False


# Global settings instance
_settings_instance = None


def get_settings() -> VantageSettings:
    """Get or create global settings instance"""
    global _settings_instance
    if _settings_instance is None:
        _settings_instance = VantageSettings()
    return _settings_instance
