"""
Vantage Traffic Enforcement System

Red light violation detection with evidence capture.
ALWAYS requires human verification. NO automated citations.
"""

from alibi.traffic.config import TrafficCameraConfig, load_traffic_cameras
from alibi.traffic.light_state import TrafficLightDetector, LightState
from alibi.traffic.vehicle_detect import VehicleDetector, TrackedVehicle
from alibi.traffic.stop_line import StopLineMonitor, CrossingEvent
from alibi.traffic.red_light_detector import RedLightViolationDetector

__all__ = [
    'TrafficCameraConfig',
    'load_traffic_cameras',
    'TrafficLightDetector',
    'LightState',
    'VehicleDetector',
    'TrackedVehicle',
    'StopLineMonitor',
    'CrossingEvent',
    'RedLightViolationDetector',
]
