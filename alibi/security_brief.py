"""
Vantage Security Advisor — the site-tailored security brief.

Answers the question a site owner actually asks: *what has been happening, and
what does it mean for the security of what I'm protecting?* — not "did anything
move". It composes what Vantage already knows, for one site:

  * the site's POSTURE (home / office / neighbourhood) — what to weight and what
    merits a human look  (see alibi/site_profile.py);
  * the site's real INCIDENTS in a time window (never invented);
  * non-personal AREA CONTEXT (§9) — background about the place, kept separate;

into deterministic, cited FINDINGS plus a short LLM-phrased narrative.

SAFETY (identical rules to explainer.py):
  * Every finding is derived DETERMINISTICALLY from real incidents and cites
    their ids. The LLM only *phrases* the assembled facts into a readable brief;
    it is never the source of the facts, so it cannot invent an incident.
  * Situational, never accusatory. Findings describe what happened and what
    merits review, never who someone is or what they intended. LLM prose is run
    through the same forbidden-language guard; on any violation (or no LLM
    available) we fall back to a deterministic template.
  * Area context is BACKGROUND about the place — attached separately, never used
    as a reason about a person.
  * Honest empty state: a quiet window says so plainly; nothing is fabricated.

Economical by design: runs on demand / periodically over already-stored
incidents — never per frame.

Nothing here raises: every path returns a valid SecurityBrief.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from alibi.schemas import Incident
from alibi.site_profile import SiteProfile, Posture
from alibi.config import VantageConfig
from alibi.validator import contains_forbidden_language
from alibi.llm_service import _ollama_available, _call_ollama, _call_anthropic

DISCLAIMER = (
    "Automated situational brief — describes what happened and what may be worth "
    "a human look. Makes no identity or intent claims; review before acting."
)

# Default "normal" day window when a site hasn't set its own hours.
_DEFAULT_OPEN_HOUR = 6
_DEFAULT_CLOSE_HOUR = 18


@dataclass
class BriefFinding:
    """A grounded, cited observation about the window."""
    kind: str                       # coverage | volume | after_hours | watchlist | severity | quiet
    detail: str                     # situational, non-accusatory
    severity_hint: str = "info"     # "info" | "review"
    incident_ids: List[str] = field(default_factory=list)   # citations to real incidents


@dataclass
class SecurityBrief:
    site_id: str
    site_name: str
    subject_type: str
    window_hours: int
    incident_count: int
    coverage: Dict[str, Any]
    findings: List[BriefFinding]
    narrative: str
    source: str                                  # "ollama" | "claude" | "template"
    brief_sections: List[str]
    area_context: Optional[Dict[str, Any]] = None
    disclaimer: str = DISCLAIMER
    generated_ts: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# --------------------------------------------------------------------------- #
# Deterministic core — assemble grounded findings from real incidents.
# --------------------------------------------------------------------------- #

def _parse_hour(value: Any, default: int) -> int:
    """Parse an 'HH:MM' (or int) hour, defaulting on anything unexpected."""
    try:
        if isinstance(value, (int, float)):
            h = int(value)
        else:
            h = int(str(value).split(":")[0])
        return h if 0 <= h <= 23 else default
    except (ValueError, TypeError, AttributeError):
        return default


def _is_after_hours(ts: datetime, open_h: int, close_h: int) -> bool:
    """Situational: is this timestamp outside the site's normal daytime window?"""
    return ts.hour < open_h or ts.hour >= close_h


def _incident_in_window(inc: Incident, cutoff: datetime) -> bool:
    try:
        return inc.created_ts >= cutoff
    except TypeError:
        return True   # naive/aware mismatch → don't silently drop real data


def _touches_site(inc: Incident, site_cameras: set) -> bool:
    """True if the incident involves one of the site's cameras. If the site has
    no cameras configured yet, every incident is in scope (honest — we say so)."""
    if not site_cameras:
        return True
    return any(getattr(e, "camera_id", None) in site_cameras for e in inc.events)


def assemble_findings(
    site: SiteProfile,
    incidents: List[Incident],
    now: Optional[datetime] = None,
    window_hours: int = 24,
) -> Dict[str, Any]:
    """Build the deterministic, cited facts. Pure — no stores, no LLM."""
    now = now or datetime.utcnow()
    cutoff = now - timedelta(hours=window_hours)
    site_cameras = set(site.camera_ids or [])

    open_h = _parse_hour((site.normal_hours or {}).get("open"), _DEFAULT_OPEN_HOUR)
    close_h = _parse_hour((site.normal_hours or {}).get("close"), _DEFAULT_CLOSE_HOUR)

    scoped = [
        inc for inc in incidents
        if _incident_in_window(inc, cutoff) and _touches_site(inc, site_cameras)
    ]

    findings: List[BriefFinding] = []
    cameras_with_activity = set()
    high, after_hours, watchlist = [], [], []

    for inc in scoped:
        for e in inc.events:
            cam = getattr(e, "camera_id", None)
            if cam and (not site_cameras or cam in site_cameras):
                cameras_with_activity.add(cam)
        if inc.get_max_severity() >= 4:
            high.append(inc.incident_id)
        if any(_is_after_hours(e.ts, open_h, close_h) for e in inc.events if getattr(e, "ts", None)):
            after_hours.append(inc.incident_id)
        if inc.has_watchlist_match():
            watchlist.append(inc.incident_id)

    coverage = {
        "cameras_configured": sorted(site_cameras),
        "cameras_with_activity": sorted(cameras_with_activity),
        "quiet_cameras": sorted(site_cameras - cameras_with_activity),
        "scoped_to_site_cameras": bool(site_cameras),
    }

    # -- Findings (each cites the real incidents behind it) ------------------- #
    if not scoped:
        findings.append(BriefFinding(
            kind="quiet",
            detail=f"No incidents recorded in the last {window_hours} hours for this site.",
            severity_hint="info",
        ))
    else:
        findings.append(BriefFinding(
            kind="volume",
            detail=f"{len(scoped)} incident(s) in the last {window_hours} hours.",
            severity_hint="info",
            incident_ids=[i.incident_id for i in scoped],
        ))
        if after_hours:
            findings.append(BriefFinding(
                kind="after_hours",
                detail=(
                    f"{len(after_hours)} occurred outside normal hours "
                    f"({open_h:02d}:00–{close_h:02d}:00) — worth a human look."
                ),
                severity_hint="review",
                incident_ids=after_hours,
            ))
        if high:
            findings.append(BriefFinding(
                kind="severity",
                detail=f"{len(high)} were higher-severity events — worth a human look.",
                severity_hint="review",
                incident_ids=high,
            ))
        if watchlist:
            findings.append(BriefFinding(
                kind="watchlist",
                detail=f"{len(watchlist)} involved a watchlist match — worth a human look.",
                severity_hint="review",
                incident_ids=watchlist,
            ))

    if site_cameras and coverage["quiet_cameras"]:
        findings.append(BriefFinding(
            kind="coverage",
            detail=(
                f"{len(coverage['quiet_cameras'])} of {len(site_cameras)} cameras "
                f"had no activity in this window."
            ),
            severity_hint="info",
        ))
    if not site_cameras:
        findings.append(BriefFinding(
            kind="coverage",
            detail="No cameras are assigned to this site yet — showing all incidents.",
            severity_hint="info",
        ))

    return {"scoped": scoped, "findings": findings, "coverage": coverage}


# --------------------------------------------------------------------------- #
# Narrative — LLM phrases the assembled facts (guarded); template fallback.
# --------------------------------------------------------------------------- #

def _template_narrative(site: SiteProfile, findings: List[BriefFinding]) -> str:
    """Deterministic prose from the assembled findings. Always safe."""
    review = [f for f in findings if f.severity_hint == "review"]
    lead = f"Security brief for {site.name} ({site.posture().label})."
    if not review:
        body = " ".join(f.detail for f in findings)
        return f"{lead} {body} Nothing in this window stands out as needing attention."
    review_text = " ".join(f.detail for f in review)
    return f"{lead} {review_text} The remaining activity appears routine."


def _build_prompt(site: SiteProfile, posture: Posture, findings: List[BriefFinding],
                  coverage: Dict[str, Any], area_render: str) -> (str, str):
    system_prompt = (
        "You are a security analyst writing a short brief for the owner of a "
        f"{posture.label.lower()}. Write ONLY from the facts provided. Every claim "
        "must trace to a listed finding — do not invent incidents, people, or "
        "outcomes. Be situational, never accusatory: describe what happened and "
        "what may be worth a human look; never state who someone is or what they "
        "intended. Area background is about the PLACE only — never treat it as a "
        "reason about a person. If the window was quiet, say so plainly. "
        "3–5 sentences, plain language."
    )
    focus = "; ".join(posture.focus)
    normal = "; ".join(posture.normal)
    facts = "\n".join(f"  - {f.detail}" for f in findings)
    parts = [
        f"SITE: {site.name} — a {posture.label.lower()}.",
        f"THIS KIND OF SITE WEIGHS: {focus}.",
        f"NORMAL HERE: {normal}.",
    ]
    # Owner-supplied context — routines, expected people/vehicles, concerns. It
    # helps judge what's normal vs worth a look; it is background, never a reason
    # to accuse anyone.
    hours = site.normal_hours or {}
    if hours.get("open") or hours.get("close"):
        parts.append(f"NORMAL HOURS: {hours.get('open', '?')}–{hours.get('close', '?')}.")
    if (site.context or "").strip():
        parts.append(f"OWNER CONTEXT (background, not evidence about anyone):\n  {site.context.strip()}")
    parts.append(f"FINDINGS (the only facts you may use):\n{facts}")
    if area_render:
        parts.append(area_render)
    return system_prompt, "\n\n".join(parts)


def build_security_brief(
    site: SiteProfile,
    incidents: List[Incident],
    area_context=None,
    config: Optional[VantageConfig] = None,
    now: Optional[datetime] = None,
    window_hours: int = 24,
) -> SecurityBrief:
    """Compose the site-tailored security brief. Testable core (takes already
    fetched incidents + optional area context). Never raises."""
    config = config or VantageConfig.from_env()
    posture = site.posture()

    assembled = assemble_findings(site, incidents, now=now, window_hours=window_hours)
    findings: List[BriefFinding] = assembled["findings"]
    coverage = assembled["coverage"]
    scoped = assembled["scoped"]

    area_dict = None
    area_render = ""
    if area_context is not None and not area_context.is_empty():
        area_dict = area_context.to_dict()
        area_render = area_context.render_for_prompt()

    def _accept(text: Optional[str]) -> Optional[str]:
        if not text:
            return None
        text = text.strip()
        if not text or contains_forbidden_language(text):
            return None
        return text

    narrative, source = None, "template"
    system_prompt, user_prompt = _build_prompt(site, posture, findings, coverage, area_render)
    try:
        if _ollama_available():
            narrative = _accept(_call_ollama(user_prompt, system_prompt, max_tokens=280, temperature=0.2))
            if narrative:
                source = "ollama"
        if not narrative and config.anthropic_api_key:
            narrative = _accept(_call_anthropic(
                system_prompt, user_prompt,
                api_key=config.anthropic_api_key,
                model=config.anthropic_model,
                max_tokens=280,
            ))
            if narrative:
                source = "claude"
    except Exception:
        narrative = None   # fail-safe

    if not narrative:
        narrative = _template_narrative(site, findings)
        source = "template"

    return SecurityBrief(
        site_id=site.site_id,
        site_name=site.name,
        subject_type=site.subject_type,
        window_hours=window_hours,
        incident_count=len(scoped),
        coverage=coverage,
        findings=findings,
        narrative=narrative,
        source=source,
        brief_sections=posture.brief_sections,
        area_context=area_dict,
        generated_ts=(now or datetime.utcnow()).isoformat(),
    )


def generate_brief_for_site(
    site_id: str,
    window_hours: int = 24,
    now: Optional[datetime] = None,
    config: Optional[VantageConfig] = None,
) -> Optional[SecurityBrief]:
    """Wire the stores: load the site, its recent incidents, and area context,
    then build the brief. Returns None if the site doesn't exist."""
    from alibi.site_profile import get_site_profile_store
    from alibi.alibi_store import get_store

    site = get_site_profile_store().get(site_id)
    if site is None:
        return None

    try:
        incidents = get_store().list_incidents(limit=500)
    except Exception:
        incidents = []

    area_context = None
    if site.area:
        try:
            from alibi.dataengine.context import get_area_context
            area_context = get_area_context(site.area)
        except Exception:
            area_context = None

    return build_security_brief(
        site, incidents, area_context=area_context,
        config=config, now=now, window_hours=window_hours,
    )
