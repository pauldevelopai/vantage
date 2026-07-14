# What Vantage Does — capability spec & acceptance checklist

> **Living document.** This is the single reference for *what Vantage is meant
> to do*. Every capability is written as a checkable statement so we can come
> back and verify the build actually works. Update the status whenever a
> capability lands or regresses.
>
> Status: ✅ built + verified · 🟡 partial / in progress · ⬜ planned
>
> Companion docs: `BUILD_PLAN.md` (the phased roadmap) · `guard.pptx` (concept).

## What Vantage is
The AI intelligence layer for cameras that helps people and police act on what
their cameras see — turning passive recording into real-time, reviewable
intelligence. **One product, two doors** (shared engine):
- ⬜ **Police / Control-Room door** — control room, watchlists, VMS, on-prem.
- ⬜ **Home / Consumer door** — connect a phone or WiFi cameras in minutes.

*(Two-door front end not built yet — the engine below is shared by both.)*

---

## 1. See — detection & tracking
- ✅ **Detects people, vehicles and objects** in a frame. *(D-FINE, Apache-2.0. Verify: 1 person@0.95 etc. on real snapshots; `alibi/vision/dfine_detector.py`, `tests/test_dfine_detector.py`.)*
- 🟡 **Tracks objects across frames** (loitering / dwell time). *(ByteTrack via ultralytics — works, but AGPL; standalone ByteTrack pending.)*

## 2. Recognise people — Digital Watchlist
- ✅ **Detects faces** in a feed. *(SCRFD, OpenCV-5 safe. Verify: 190 faces on snapshots.)*
- ✅ **Generates real face embeddings** (ArcFace, 512-d). *(`face_embed.py`, `tests/test_face_arcface.py`.)*
- ✅ **Matches faces against a police watchlist** (cosine, conservative threshold). *(`face_match.py`, `tests/test_watchlist.py`.)*
- ✅ **"Have these people been involved before?"** — searches the sighting archive for prior appearances and summarises (times seen, cameras, watchlist match). *(`patterns/person_history.py`, `tests/test_person_history.py`.)*

## 3. Vehicles — Vehicle Intelligence
- ✅ **Reads number plates** (detect + OCR). *(FastALPR, ONNX. Verify: `N12345W` read end-to-end.)*
- ✅ **Flags hotlist plate matches** (human review, no auto-action). *(`plates/hotlist_store.py`, `tests/test_hotlist_plates.py`.)*
- ✅ **Impossible-travel** — same plate two places too far apart to reach. *(`plates/travel_detector.py`, `cameras/cross_camera.py`.)*
- ✅ **Colour mismatch vs. registration** — plate registered to a black car, camera sees white. *(`vehicles/mismatch.py`, `tests/test_color_mismatch.py`.)*
- ⬜ **Make/model mismatch** — needs a vehicle classifier (VLM) heavier than the current box.

## 4. Connect the dots — Pattern Detection *(Phase 2)*
- ✅ **Same vehicle/person matched across cameras by appearance** (ReID, no plate needed). *(OSNet, `cameras/appearance_reid.py`, `tests/test_cross_camera_reid.py`.)*
- ✅ **"What's been happening in the last hour / 24h / week"** — windowed activity summary (people, vehicles, plate reads, watchlist hits, busiest camera + time), shown in the Control Room's **Patterns** page. *(`patterns/activity_patterns.py` + `patterns/api.py` + console `PatternsPage.tsx`; `tests/test_activity_patterns.py`.)*
- ✅ **Co-occurrence** — "this vehicle/person was near N incidents" (same camera, within a time window). *(`patterns/co_occurrence.py`, `tests/test_co_occurrence.py`.)*
- ⬜ **"Why flagged" explainer** on every alert — grounded, cited, human-in-the-loop.

## 5. Read behaviour — Behaviour & Threat *(Phase 3)*
- ⬜ **Suspicious behaviour vs. just walking** (running, loitering, following, fighting).
- ⬜ **"Possibly armed" guess** — weapon detection. ⚠️ highest-liability feature: always "possible", always human-confirmed, always logged.

## 6. Advise — Security Advisor *(Phase 4)*
- ⬜ **Suggestions to improve your security** — coverage gaps, blind spots, prioritised recommendations.

## 7. Connect anything — Universal Ingest *(Phase 5)*
- 🟡 **RTSP / IP cameras**. *(`video/rtsp_reader.py`.)*
- ⬜ **Auto-discover cameras on your WiFi** (ONVIF/RTSP LAN scan, one-click connect).
- 🟡 **Use a phone as a camera**. *(`mobile_camera*.py`.)*
- ⬜ **Connect any other device in the house**.

## 8. Stay safe — always-on guarantees
- ✅ **Never accuses** — output is "possible / appears / needs review", never "suspect/criminal". *(`validator.py`, `tests/test_alibi_engine_validation.py`.)*
- ✅ **Human review before dispatch** — high-risk actions require a person. *(validator rules.)*
- ✅ **Auditable** — append-only logs of decisions. *(`alibi_store.py`.)*
- ✅ **Encrypted at rest**. *(`encryption.py`.)*

---

## How to check the build is working
1. **Tests:** `pytest tests/ -q` (skips heavy-model tests when their deps are absent).
2. **Per capability:** the "Verify:" note above names the module + test for each.
3. **Live:** load the deployed app and exercise the flow (see `BUILD_PLAN.md` deploy steps). No-fake-data rule: empty states are honest, never mocked.
