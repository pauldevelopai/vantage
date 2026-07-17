"""
Licence guard.

ultralytics is AGPL-3.0 — unworkable for a commercial deployment. It used to do
the tracking (`model.track()` runs ByteTrack internally and returns boxes with
ids). Detection already moved to D-FINE (Apache-2.0); this pins that tracking
did too, and that nothing on a live path reaches for ultralytics again.
"""

import ast
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[1] / "alibi"

# Paths that run in production. simulate.py is a dev tool; gatekeeper keeps an
# optional YOLO fallback for anyone who chooses to install it themselves.
LIVE_PATHS = [
    "mobile_camera_enhanced.py",
    "vision/frame_intelligence.py",
    "vision/simple_tracker.py",
    "vision/tracking.py",
    "cameras/frame_analyzer.py",
    "cameras/record_agent.py",
    "cameras/recorder.py",
]


def _imports(path: pathlib.Path):
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                yield a.name
        elif isinstance(node, ast.ImportFrom):
            yield node.module or ""


def test_no_live_path_imports_ultralytics():
    offenders = []
    for rel in LIVE_PATHS:
        p = REPO / rel
        if not p.exists():
            continue
        for mod in _imports(p):
            if mod and mod.split(".")[0] == "ultralytics":
                offenders.append(rel)
    assert not offenders, f"AGPL (ultralytics) imported on live paths: {offenders}"


def test_ultralytics_is_not_a_declared_dependency():
    req = (REPO.parent / "requirements.txt").read_text()
    declared = [l for l in req.splitlines()
                if l.strip() and not l.strip().startswith("#") and "ultralytics" in l]
    assert not declared, f"ultralytics still declared: {declared}"


def test_the_fallbacks_are_optional_not_required():
    # gatekeeper/simulate may reference YOLO, but only guarded — so the code runs
    # (and the licence stays clean) with ultralytics absent.
    for rel in ("vision/gatekeeper.py", "vision/simulate.py"):
        src = (REPO / rel).read_text()
        if "ultralytics" in src:
            assert "ImportError" in src, f"{rel} imports ultralytics unguarded"


def test_tracking_works_with_no_yolo_installed():
    """Detections in (from any detector), TrackState out — the shape rules and
    incidents consume. A new track is confirmed on its second frame (pending
    until min_hits), which is the tracker's long-standing behaviour."""
    from datetime import datetime, timedelta
    from alibi.vision.tracking import MultiObjectTracker, TrackState
    from alibi.vision.simple_tracker import Detection
    t = MultiObjectTracker(min_hits=1)
    T0 = datetime(2026, 7, 17, 8, 0, 0)
    def det(x):
        return Detection(bbox=(x, 100, 40, 80), confidence=0.9, class_name="person")
    t.update([det(100)], timestamp=T0)                       # pending
    tracks = t.update([det(104)], timestamp=T0 + timedelta(seconds=1))   # confirmed
    assert len(tracks) == 1
    state = list(tracks.values())[0]
    assert isinstance(state, TrackState)                     # rules still get TrackState
    assert state.class_name == "person"
