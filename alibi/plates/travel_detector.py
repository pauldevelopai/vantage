"""
Impossible Travel Detection

Detects when the same license plate is seen at two different camera locations
within an impossibly short time window, indicating potential plate cloning.
"""

from datetime import datetime
from typing import Optional, Dict, Tuple
from dataclasses import dataclass


@dataclass
class TravelAlert:
    """Alert when impossible travel is detected"""
    plate: str
    camera_a: str
    time_a: str  # ISO timestamp
    camera_b: str
    time_b: str  # ISO timestamp
    seconds_between: float
    message: str


# Default: 5 minutes is the minimum realistic travel time between any two cameras
DEFAULT_MIN_TRAVEL_SECONDS = 300


class ImpossibleTravelDetector:
    """
    Detects impossible travel by tracking plate sightings across cameras.

    If the same plate appears at two different cameras within the minimum
    travel time, it flags as suspicious (possible plate cloning).
    """

    def __init__(self, min_travel_seconds: float = DEFAULT_MIN_TRAVEL_SECONDS):
        self.min_travel_seconds = min_travel_seconds
        # {normalized_plate: (camera_id, timestamp_iso)}
        self._last_sightings: Dict[str, Tuple[str, str]] = {}

    def check(self, plate: str, camera_id: str, timestamp: str) -> Optional[TravelAlert]:
        """
        Check a plate sighting for impossible travel.

        Args:
            plate: Normalized plate text
            camera_id: Camera that detected the plate
            timestamp: ISO timestamp of detection

        Returns:
            TravelAlert if impossible travel detected, None otherwise
        """
        if not plate or not camera_id:
            return None

        prev = self._last_sightings.get(plate)

        # Update last sighting
        self._last_sightings[plate] = (camera_id, timestamp)

        if prev is None:
            return None

        prev_camera, prev_ts = prev

        # Same camera — not impossible travel
        if prev_camera == camera_id:
            return None

        # Calculate time difference
        try:
            t_prev = datetime.fromisoformat(prev_ts)
            t_now = datetime.fromisoformat(timestamp)
            seconds_between = abs((t_now - t_prev).total_seconds())
        except (ValueError, TypeError):
            return None

        # Check if travel time is impossible
        if seconds_between < self.min_travel_seconds:
            return TravelAlert(
                plate=plate,
                camera_a=prev_camera,
                time_a=prev_ts,
                camera_b=camera_id,
                time_b=timestamp,
                seconds_between=seconds_between,
                message=(
                    f"Possible plate cloning: {plate} seen at {prev_camera} "
                    f"and {camera_id} within {int(seconds_between)}s "
                    f"(minimum expected: {int(self.min_travel_seconds)}s)"
                ),
            )

        return None

    def get_recent_sightings(self) -> Dict[str, Tuple[str, str]]:
        """Return current sighting cache for inspection."""
        return dict(self._last_sightings)
