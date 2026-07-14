"""
Vantage Data Engine — place-context lookup (§9 consumer).

Turns ingested places/context records into ADVISORY BACKGROUND for a reviewer
looking at an incident.

⚠️ THE RULE THAT MATTERS
Area context is background about a PLACE. It is never a reason a person or
vehicle was flagged, and it must never be attributed to the detected individual.
Treating "this suburb has high vehicle-theft stats" as evidence about the person
in frame is profiling-by-neighbourhood — exactly what Vantage's safety posture
exists to prevent. So:

  * context is returned SEPARATELY from the explainer's `reasons` and is never
    merged into them;
  * it is labelled as background in the UI and in the prompt;
  * an UNAVAILABLE / empty context is stated honestly — never treated as
    reassurance, never filled with invented content.

This mirrors the ContextBundle rule already used in `llm_service._build_alert_prompt`.
"""

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

from alibi.dataengine.schemas import DataDomain
from alibi.dataengine.store import DataEngineStore

CONTEXT_RULE = (
    "Background about the AREA only. It is not evidence about the detected "
    "person or vehicle and must not be attributed to them."
)


@dataclass
class ContextItem:
    """One cited piece of area background."""
    kind: str                    # "crime_stats" | "poi"
    detail: str                  # neutral human phrasing
    citation: Dict[str, Any] = field(default_factory=dict)  # source + provenance


@dataclass
class AreaContext:
    area: str
    items: List[ContextItem] = field(default_factory=list)
    rule: str = CONTEXT_RULE

    def is_empty(self) -> bool:
        return not self.items

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def render_for_prompt(self) -> str:
        """Render for an LLM prompt, carrying the rule with it."""
        if self.is_empty():
            return ""
        lines = "\n".join(f"  - {i.detail}" for i in self.items)
        return (
            f"AREA BACKGROUND for {self.area} ({CONTEXT_RULE}):\n{lines}"
        )


def get_area_context(
    area: str,
    store: Optional[DataEngineStore] = None,
    limit: int = 5,
) -> AreaContext:
    """Look up non-personal place-context for an area.

    Honest empty state: an unknown area, or an engine with no ingested data,
    returns an AreaContext with no items — never invented background.
    """
    ctx = AreaContext(area=area or "")
    if not area:
        return ctx

    store = store or DataEngineStore()
    target = area.strip().lower()

    try:
        records = store.query(domain=DataDomain.PLACES_CONTEXT)
    except Exception:
        return ctx  # fail-safe: no context rather than a crash

    for rec in records:
        p = rec.payload

        # Crime statistics for this area (aggregate, non-personal)
        rec_area = str(p.get("area", "")).strip().lower()
        if rec_area and rec_area == target and p.get("count") is not None:
            period = p.get("period", "the reported period")
            category = p.get("crime_category", "incidents")
            ctx.items.append(ContextItem(
                kind="crime_stats",
                detail=(
                    f"Published statistics for {p['area']} record "
                    f"{p['count']} {category} in {period}."
                ),
                citation={
                    "source_id": rec.source_id,
                    "record_id": rec.record_id,
                    "lawful_basis": rec.lawful_basis.value,
                    "source_url": rec.provenance.get("source_url"),
                },
            ))

        # Nearby points of interest (police stations etc.) — useful to a reviewer
        place_area = str(p.get("address", "")).strip().lower()
        if p.get("place_name") and (target in place_area or rec_area == target):
            ctx.items.append(ContextItem(
                kind="poi",
                detail=f"Nearby: {p['place_name']} ({p.get('category', 'point of interest')}).",
                citation={
                    "source_id": rec.source_id,
                    "record_id": rec.record_id,
                    "lawful_basis": rec.lawful_basis.value,
                    "source_url": rec.provenance.get("source_url"),
                },
            ))

        if len(ctx.items) >= limit:
            break

    return ctx


def resolve_area_for_camera(camera_id: str) -> str:
    """Map a camera to its configured area. Empty when unset — no guessing."""
    try:
        from alibi.cameras.camera_store import get_camera_store
        cam = get_camera_store().get(camera_id)
        return (cam.area or "") if cam else ""
    except Exception:
        return ""
