"""
Vantage Vehicle Sightings System

Continuous vehicle detection, attribute extraction, and searchable indexing.
Enables operators to search vehicle history by make, model, color.
"""

from alibi.vehicles.vehicle_detect import VehicleDetector, DetectedVehicle
from alibi.vehicles.vehicle_attrs import VehicleAttributeExtractor, VehicleAttributes
from alibi.vehicles.sightings_store import VehicleSightingsStore, VehicleSighting

__all__ = [
    'VehicleDetector',
    'DetectedVehicle',
    'VehicleAttributeExtractor',
    'VehicleAttributes',
    'VehicleSightingsStore',
    'VehicleSighting',
]
