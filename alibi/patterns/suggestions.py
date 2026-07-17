"""
Ways to improve your security setup — deterministic, cited, honest.

Every suggestion is derived from a REAL observed gap in this deployment's own
configuration or data (never generic filler), says why it matters using the
actual numbers, and links to the page that fixes it. When nothing is missing,
the list is honestly empty — we never invent advice to fill a panel.
"""

from __future__ import annotations

from typing import Any, Dict, List


def security_suggestions(
    sites: List[Any],
    cameras: List[Any],
    enrolled_faces: int,
    face_sightings_ever: int,
    person_events_window: int,
    hotlist_count: int,
    cameras_with_area: int,
) -> List[Dict[str, str]]:
    """Rule-based suggestions from the deployment's real state. Pure."""
    out: List[Dict[str, str]] = []

    site = sites[0] if sites else None
    if site is None:
        out.append({
            "title": "Create your site profile",
            "why": "No site is set up yet, so the system has no posture to judge activity against.",
            "link": "/sites", "action": "Set up on Sites",
        })
    else:
        if not (site.normal_hours or {}).get("open"):
            out.append({
                "title": "Set your normal hours",
                "why": (f"“{site.name}” has no normal hours, so the after-hours "
                        f"presence trigger is armed but cannot evaluate — night-time "
                        f"activity currently looks the same as daytime."),
                "link": "/sites", "action": "Set hours on Sites",
            })

    if enrolled_faces == 0:
        out.append({
            "title": "Enrol the people who belong here",
            "why": ("No one is enrolled on Faces yet, so every person is an "
                    "“Unknown person”. Enrolling household members means strangers "
                    "stand out instead of blending in."),
            "link": "/faces", "action": "Enrol on Faces",
        })

    if person_events_window > 0 and face_sightings_ever == 0:
        out.append({
            "title": "No camera catches faces",
            "why": (f"{person_events_window} person events in this window but not one "
                    f"readable face ever — people appear at a distance in wide views. "
                    f"A camera at door height near the entrance would let recognition "
                    f"and person-history actually work."),
            "link": "/cameras", "action": "Review camera placement",
        })

    offline = [c for c in cameras if getattr(c, "status", "") not in ("online", "active", "")
               and getattr(c, "enabled", True) is False]
    for c in offline[:2]:
        out.append({
            "title": f"Camera “{getattr(c, 'name', c)}” is disabled",
            "why": "A disabled camera is a blind spot the rest of the system can't cover.",
            "link": "/cameras", "action": "Check on Cameras",
        })

    if hotlist_count == 0:
        out.append({
            "title": "Add plates to your hotlist",
            "why": ("The plate reader is running but the hotlist is empty — a known "
                    "problem vehicle would currently pass unremarked."),
            "link": "/hotlist", "action": "Add on Hotlist",
        })

    if cameras and cameras_with_area == 0:
        out.append({
            "title": "Set your cameras' area",
            "why": ("No camera has its area (suburb) set, so incidents carry no "
                    "local context and the weekly area-data refresh has nothing to fetch."),
            "link": "/cameras", "action": "Set area on Cameras",
        })

    return out
