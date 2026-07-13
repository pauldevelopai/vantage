"""
BaselineContextProvider - "is this normal for this camera at this hour?"

Uses the learned per-camera/per-hour activity baseline (activity_baseline.py).
An observation well outside the learned norm is a caution signal and forces
human review. If no baseline has been learned yet, the item is ABSENT (honest)
- never PRESENT-with-reassurance.
"""

from typing import List, Optional

from alibi.schemas import Incident
from alibi.config import VantageConfig
from alibi.activity_baseline import get_baseline_engine
from alibi.context.schemas import Availability, ContextItem
from alibi.context.provider import ContextProvider
from alibi.context.providers._incident_signals import (
    latest_camera_and_ts,
    observed_counts,
    threat_level_from_severity,
)


class BaselineContextProvider(ContextProvider):
    name = "activity_baseline"

    def fetch(self, incident: Incident, config: Optional[VantageConfig] = None) -> List[ContextItem]:
        camera_id, _zone, ts = latest_camera_and_ts(incident)
        if not camera_id:
            return [ContextItem(
                provider=self.name, label="Activity baseline",
                availability=Availability.ABSENT,
                source="learned baseline",
                metadata={"reason": "no camera on incident"},
            )]

        person_count, vehicle_count = observed_counts(incident)
        threat = threat_level_from_severity(incident)

        engine = get_baseline_engine()
        score = engine.score_observation(
            camera_id=camera_id,
            person_count=person_count,
            vehicle_count=vehicle_count,
            threat_level=threat,
            timestamp=ts,
        )

        # No usable baseline yet -> honest ABSENT, not a false "normal".
        if score.baseline_sample_count == 0:
            return [ContextItem(
                provider=self.name, label="Activity baseline",
                availability=Availability.ABSENT,
                source="learned baseline",
                as_of=ts,
                metadata={"reason": "no baseline learned for this camera/time yet"},
            )]

        hour = ts.hour if ts else 0
        if score.is_anomalous:
            return [ContextItem(
                provider=self.name, label="Activity baseline",
                availability=Availability.PRESENT,
                summary=(
                    f"Activity here appears unusual for ~{hour:02d}:00 "
                    f"(deviation {score.combined_score:.1f}sigma vs learned norm; "
                    f"persons z={score.person_z_score:+.1f}, vehicles z={score.vehicle_z_score:+.1f})."
                ),
                source=f"learned baseline ({score.baseline_sample_count} samples)",
                as_of=ts,
                caution_signals=["activity_anomaly_vs_baseline"],
                elevate_review=True,
                metadata=score.to_dict(),
            )]

        # Within norm: informational only. Caution-only means we never use this
        # to downgrade the incident, just to inform the operator.
        return [ContextItem(
            provider=self.name, label="Activity baseline",
            availability=Availability.PRESENT,
            summary=f"Activity here appears within the normal range for ~{hour:02d}:00.",
            source=f"learned baseline ({score.baseline_sample_count} samples)",
            as_of=ts,
            metadata=score.to_dict(),
        )]
