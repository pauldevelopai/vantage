"""
Tests for the Security Advisor brief — the site-tailored "what has been
happening and what does it mean for your security" composition.

Focus on the DETERMINISTIC, grounded core (findings assembled from real
incidents, cited by id) and the safety properties: situational not accusatory,
honest empty state, area context kept separate, always fail-safe to a template.
No LLM is available in the test env, so the narrative deterministically uses the
template path.
"""

from datetime import datetime, timedelta

from alibi.schemas import Incident, IncidentStatus, CameraEvent
from alibi.site_profile import SiteProfile
from alibi.security_brief import (
    build_security_brief,
    assemble_findings,
    BriefFinding,
)
from alibi.validator import contains_forbidden_language


NOW = datetime(2026, 7, 15, 12, 0, 0)


def _event(camera_id="cam1", hour=12, severity=2, event_type="person_detected", watchlist=False):
    return CameraEvent(
        event_id=f"ev_{camera_id}_{hour}_{severity}",
        camera_id=camera_id,
        ts=datetime(2026, 7, 15, hour, 0, 0),
        zone_id="z1",
        event_type=event_type,
        confidence=0.9,
        severity=severity,
        metadata={"watchlist_match": watchlist},
    )


def _incident(incident_id, events, created_hour=12):
    ts = datetime(2026, 7, 15, created_hour, 0, 0)
    return Incident(
        incident_id=incident_id,
        status=IncidentStatus.NEW,
        created_ts=ts,
        updated_ts=ts,
        events=events,
    )


def _site(subject_type="home", cameras=None, hours=None):
    return SiteProfile(
        site_id="site_test",
        name="Test Site",
        subject_type=subject_type,
        area="",
        camera_ids=cameras or [],
        normal_hours=hours or {},
    )


# --- empty / honest state -------------------------------------------------- #

def test_quiet_window_is_honest():
    brief = build_security_brief(_site(), [], now=NOW)
    assert brief.incident_count == 0
    assert any(f.kind == "quiet" for f in brief.findings)
    assert brief.source == "template"
    assert "No incidents" in brief.findings[0].detail
    # never fabricates activity
    assert "worth a human look" not in brief.narrative.lower()


def test_old_incidents_excluded_from_window():
    old = _incident("inc_old", [_event(hour=12)], created_hour=12)
    old.created_ts = NOW - timedelta(hours=48)   # outside 24h window
    brief = build_security_brief(_site(), [old], now=NOW, window_hours=24)
    assert brief.incident_count == 0


# --- grounded findings, cited by id ---------------------------------------- #

def test_findings_cite_real_incident_ids():
    incs = [
        _incident("inc_1", [_event(camera_id="cam1", hour=12, severity=2)]),
        _incident("inc_2", [_event(camera_id="cam1", hour=3, severity=5)]),  # after-hours + high sev
    ]
    out = assemble_findings(_site(cameras=["cam1"]), incs, now=NOW)
    volume = next(f for f in out["findings"] if f.kind == "volume")
    assert set(volume.incident_ids) == {"inc_1", "inc_2"}
    after = next(f for f in out["findings"] if f.kind == "after_hours")
    assert after.incident_ids == ["inc_2"]         # only the 03:00 one
    assert after.severity_hint == "review"
    sev = next(f for f in out["findings"] if f.kind == "severity")
    assert sev.incident_ids == ["inc_2"]


def test_after_hours_respects_site_hours():
    # An office open 07–19: an 06:00 event is after-hours; a 12:00 one is not.
    site = _site("office", cameras=["cam1"], hours={"open": "07:00", "close": "19:00"})
    incs = [
        _incident("inc_early", [_event(camera_id="cam1", hour=6)]),
        _incident("inc_mid", [_event(camera_id="cam1", hour=12)]),
    ]
    out = assemble_findings(site, incs, now=NOW)
    after = next(f for f in out["findings"] if f.kind == "after_hours")
    assert after.incident_ids == ["inc_early"]


def test_watchlist_finding():
    incs = [_incident("inc_w", [_event(camera_id="cam1", watchlist=True)])]
    out = assemble_findings(_site(cameras=["cam1"]), incs, now=NOW)
    w = next(f for f in out["findings"] if f.kind == "watchlist")
    assert w.incident_ids == ["inc_w"]
    assert w.severity_hint == "review"


# --- camera scoping -------------------------------------------------------- #

def test_scoping_to_site_cameras():
    incs = [
        _incident("inc_mine", [_event(camera_id="cam1")]),
        _incident("inc_other", [_event(camera_id="camX")]),   # not this site
    ]
    out = assemble_findings(_site(cameras=["cam1"]), incs, now=NOW)
    volume = next(f for f in out["findings"] if f.kind == "volume")
    assert volume.incident_ids == ["inc_mine"]
    assert out["coverage"]["cameras_with_activity"] == ["cam1"]


def test_no_cameras_configured_shows_all_and_says_so():
    incs = [_incident("inc_1", [_event(camera_id="camX")])]
    brief = build_security_brief(_site(cameras=[]), incs, now=NOW)
    assert brief.incident_count == 1
    assert any(f.kind == "coverage" and "No cameras are assigned" in f.detail
               for f in brief.findings)
    assert brief.coverage["scoped_to_site_cameras"] is False


def test_quiet_cameras_reported():
    incs = [_incident("inc_1", [_event(camera_id="cam1")])]
    out = assemble_findings(_site(cameras=["cam1", "cam2", "cam3"]), incs, now=NOW)
    assert out["coverage"]["quiet_cameras"] == ["cam2", "cam3"]
    cov = next(f for f in out["findings"] if f.kind == "coverage")
    assert "2 of 3 cameras" in cov.detail


# --- safety ---------------------------------------------------------------- #

def test_findings_and_narrative_never_accuse():
    incs = [
        _incident("inc_1", [_event(camera_id="cam1", hour=2, severity=5, watchlist=True)]),
    ]
    brief = build_security_brief(_site(cameras=["cam1"]), incs, now=NOW)
    for f in brief.findings:
        assert not contains_forbidden_language(f.detail), f.detail
    assert not contains_forbidden_language(brief.narrative)


def test_brief_is_serializable_and_tagged():
    incs = [_incident("inc_1", [_event(camera_id="cam1")])]
    brief = build_security_brief(_site("neighbourhood", cameras=["cam1"]), incs, now=NOW)
    d = brief.to_dict()
    assert d["subject_type"] == "neighbourhood"
    assert d["generated_ts"] == NOW.isoformat()
    assert d["disclaimer"]
    assert isinstance(d["findings"], list) and isinstance(d["findings"][0], dict)
    # brief_sections come from the neighbourhood posture
    assert "cross-property correlations" in d["brief_sections"]


def test_area_context_kept_separate_when_present():
    from alibi.dataengine.context import AreaContext, ContextItem
    ctx = AreaContext(area="Parkview", items=[
        ContextItem(kind="crime_stats", detail="Published statistics for Parkview record 5 incidents.",
                    citation={"source_id": "s1"}),
    ])
    incs = [_incident("inc_1", [_event(camera_id="cam1")])]
    brief = build_security_brief(_site(cameras=["cam1"]), incs, area_context=ctx, now=NOW)
    # area context is attached separately, never folded into findings
    assert brief.area_context is not None
    assert brief.area_context["area"] == "Parkview"
    for f in brief.findings:
        assert "Parkview" not in f.detail
