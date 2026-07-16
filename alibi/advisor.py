"""
Security Advisor (Phase 4) — "how do I improve my security?"

Reviews the REAL state of a deployment — is anything actually recording, are the
cameras attached to a site, is the site telling the AI what normal looks like, is
anything being watched for — and returns prioritised, plain-English
recommendations.

Rules it follows, deliberately:
  * Every recommendation is DERIVED FROM OBSERVED STATE and carries the evidence
    that triggered it. Nothing is generic advice; nothing is invented.
  * If the deployment is in good shape, it says so and returns nothing. An advisor
    that always finds something to say is just noise.
  * It advises on the SYSTEM (coverage, configuration, blind spots) — never on
    people. It cannot recommend anything about a person, by construction.

`build_recommendations` is pure: it takes a plain state dict and returns
dataclasses. No stores, no LLM, no network — so the judgement is unit-testable and
deterministic.
"""

from dataclasses import dataclass, asdict, field
from typing import Any, Dict, List, Optional

# Priority ordering for sorting: the thing that means "you have no security at all"
# must outrank a nice-to-have.
_PRIORITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}


@dataclass
class Recommendation:
    key: str
    title: str                 # plain English, imperative
    detail: str                # what we observed, in the owner's terms
    priority: str              # critical | high | medium | low
    evidence: str              # the specific fact that triggered this
    action: str = ""           # what to actually do
    link: str = ""             # where in the console to do it

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def build_recommendations(state: Dict[str, Any]) -> List[Recommendation]:
    """Derive recommendations from observed state.

    `state` keys (all optional; absent = unknown, and we stay quiet rather than
    guess):
      recorders_total / recorders_online : int
      cameras_total : int
      cameras_unassigned : list[str]     — registered but on no site
      sites : list of {name, camera_ids, has_context, has_hours, area}
      quiet_cameras : list[str]          — on a site but no activity in the window
      window_hours : int
      hotlist_count : int
      watchlist_count : int
      incident_count : int
      intel_sources : int                — connected external context sources
      vision_backend : str               — e.g. "claude" | "basic_cv"
    """
    recs: List[Recommendation] = []

    recorders_total = state.get("recorders_total")
    recorders_online = state.get("recorders_online")
    cameras_total = state.get("cameras_total")
    window = state.get("window_hours", 24)

    # --- Is anything actually being watched at all? ------------------------- #
    if recorders_total == 0:
        recs.append(Recommendation(
            key="no_recorder",
            title="Nothing is recording yet",
            detail="No recorder has been set up, so no footage is being captured or analysed.",
            priority="critical",
            evidence="0 recorders registered.",
            action="Set up a recorder on an always-on computer on your camera network.",
            link="/recorders",
        ))
    elif recorders_online == 0:
        recs.append(Recommendation(
            key="recorder_offline",
            title="Your recorder is offline",
            detail="Nothing is being recorded or analysed while it's down — you have no cover right now.",
            priority="critical",
            evidence=f"{recorders_total} recorder(s) registered, none online.",
            action="Start the recorder again on that computer.",
            link="/recorders",
        ))

    if cameras_total == 0:
        recs.append(Recommendation(
            key="no_cameras",
            title="No cameras added",
            detail="Vantage has no cameras to watch.",
            priority="critical",
            evidence="0 cameras registered.",
            action="Scan your network to find your cameras.",
            link="/cameras",
        ))

    # --- The AI is only as good as what it's told about the place ----------- #
    if state.get("vision_backend") == "basic_cv":
        recs.append(Recommendation(
            key="weak_vision",
            title="Scene understanding is running on a fallback",
            detail=("Without a vision model, Vantage can only judge frames by crude brightness "
                    "changes, so descriptions and alerts will be poor."),
            priority="high",
            evidence="No vision model configured — using the basic-CV fallback.",
            action="Set an ANTHROPIC_API_KEY on the server to enable proper scene understanding.",
            link="/settings",
        ))

    unassigned = state.get("cameras_unassigned") or []
    if unassigned:
        recs.append(Recommendation(
            key="cameras_unassigned",
            title=f"{len(unassigned)} camera{'s' if len(unassigned) != 1 else ''} not attached to a site",
            detail=("A camera that isn't on a site gets no site tailoring — the AI doesn't know "
                    "whether it's watching a home, an office, or a street, so it can't judge what's normal."),
            priority="high",
            evidence="Unassigned: " + ", ".join(unassigned[:6]) + ("…" if len(unassigned) > 6 else ""),
            action="Assign each camera to the site it watches.",
            link="/sites",
        ))

    for site in (state.get("sites") or []):
        name = site.get("name", "a site")
        if not site.get("camera_ids"):
            recs.append(Recommendation(
                key=f"site_no_cameras:{name}",
                title=f"“{name}” has no cameras",
                detail="This site isn't watching anything, so it will never produce a brief.",
                priority="high",
                evidence=f"Site “{name}” has 0 cameras assigned.",
                action="Tick the cameras this site watches.",
                link="/sites",
            ))
            continue
        if not site.get("has_hours"):
            recs.append(Recommendation(
                key=f"site_no_hours:{name}",
                title=f"Tell Vantage when “{name}” is normally active",
                detail=("Without normal hours, after-hours activity can't be weighted — someone at "
                        "the gate at 3am reads the same as midday."),
                priority="medium",
                evidence=f"Site “{name}” has no normal hours set.",
                action="Set the site's normal hours.",
                link="/sites",
            ))
        if not site.get("has_context"):
            recs.append(Recommendation(
                key=f"site_no_context:{name}",
                title=f"Add context for “{name}”",
                detail=("A few lines about who's normally there, known vehicles and routines lets the "
                        "AI tell ordinary life apart from something worth your attention."),
                priority="medium",
                evidence=f"Site “{name}” has no context set.",
                action="Add site context (background only — never used to accuse anyone).",
                link="/sites",
            ))
        if not site.get("area"):
            recs.append(Recommendation(
                key=f"site_no_area:{name}",
                title=f"Set the area for “{name}”",
                detail="The area links local context to this site's brief.",
                priority="low",
                evidence=f"Site “{name}” has no area set.",
                action="Set the suburb/area on the site.",
                link="/sites",
            ))

    # --- Blind spots: a camera on a site that saw nothing ------------------- #
    quiet = state.get("quiet_cameras") or []
    if quiet and state.get("incident_count", 0) > 0:
        # Only meaningful when OTHER cameras did see things — otherwise it was
        # simply a quiet window and there is nothing to report.
        recs.append(Recommendation(
            key="quiet_cameras",
            title=f"{len(quiet)} camera{'s' if len(quiet) != 1 else ''} saw nothing while others did",
            detail=("Worth checking these are actually working and pointed where you think — a camera "
                    "that never triggers can be a blind spot rather than a quiet corner."),
            priority="medium",
            evidence=f"No activity in {window}h from: " + ", ".join(quiet[:6]) + ("…" if len(quiet) > 6 else ""),
            action="Check the live view for each.",
            link="/sites",
        ))

    # --- Things that only pay off if you switch them on --------------------- #
    if state.get("hotlist_count") == 0:
        recs.append(Recommendation(
            key="empty_hotlist",
            title="No plates are being watched for",
            detail=("Your cameras read plates already, but nothing is flagged, so a plate you care "
                    "about would pass unnoticed."),
            priority="medium",
            evidence="Hotlist is empty.",
            action="Add a plate to the hotlist.",
            link="/hotlist",
        ))
    if state.get("watchlist_count") == 0:
        recs.append(Recommendation(
            key="empty_watchlist",
            title="No one is enrolled on the watchlist",
            detail=("Faces are detected already, but with nobody enrolled they stay unknown — you'll "
                    "see continuity (“seen 4 times”), never a name."),
            priority="low",
            evidence="Watchlist is empty.",
            action="Enrol someone you want to be told about.",
            link="/watchlist",
        ))
    if state.get("intel_sources") == 0:
        recs.append(Recommendation(
            key="no_intel",
            title="No local context connected",
            detail=("Vantage can weigh what your cameras see against what's actually common in your "
                    "area — but no context source is connected."),
            priority="low",
            evidence="0 intel sources connected.",
            action="Add a data source, or start with one marked “Can do now”.",
            link="/intel",
        ))

    recs.sort(key=lambda r: (_PRIORITY_RANK.get(r.priority, 9), r.key))
    return recs


def summarise(recs: List[Recommendation]) -> str:
    """One honest line for the top of the page."""
    if not recs:
        return "Nothing to improve right now — your setup looks sound."
    crit = sum(1 for r in recs if r.priority == "critical")
    high = sum(1 for r in recs if r.priority == "high")
    if crit:
        return (f"{crit} thing{'s' if crit != 1 else ''} need{'' if crit != 1 else 's'} attention now — "
                "your cover is incomplete until they're fixed.")
    if high:
        return f"{high} important improvement{'s' if high != 1 else ''} would make a real difference."
    return f"{len(recs)} suggestion{'s' if len(recs) != 1 else ''} to get more out of Vantage."
