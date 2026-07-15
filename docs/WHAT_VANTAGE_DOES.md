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

**AI model tier (natural-language alerts, shift reports, scene descriptions):**
local **Ollama** first (data stays in-country) → **Claude / Anthropic** as the
preferred cloud model → OpenAI as an optional fallback. Set `ANTHROPIC_API_KEY`
to enable the cloud tier; `ANTHROPIC_TEXT_MODEL` / `ANTHROPIC_VISION_MODEL`
override the default (`claude-opus-4-8`). *(`llm_service.py`,
`vision/scene_analyzer.py`, `tests/test_claude_llm.py`.)*

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
- ✅ **"Why flagged" explainer** on every alert — grounded, cited, human-in-the-loop. Reasons are extracted deterministically from the incident's real signals (each cited to an event/evidence/plan field); the LLM only phrases them, guarded by the forbidden-language validator with a real-data template fallback. *(`explainer.py`, `/incidents/{id}/explanation`, IncidentDetailPage "Why was this flagged?" panel, `tests/test_explainer.py`.)*

## 5. Read behaviour — Behaviour & Threat *(Phase 3)*
- ⬜ **Suspicious behaviour vs. just walking** (running, loitering, following, fighting).
- ⬜ **"Possibly armed" guess** — weapon detection. ⚠️ highest-liability feature: always "possible", always human-confirmed, always logged.

## 6. Advise — site-tailored security intelligence *(Phase 4)*
The payoff of everything else: ongoing, grounded intelligence about *what the
cameras are seeing and what it means for the security of what's being watched
over* — not a motion alarm. Motion is only the cheap trigger; the intelligence
is deep, and it runs on **events** + **periodic synthesis** (not per-frame), so
it stays economical — a quiet site costs ~nothing.

- ✅ **Site profile — what's being protected.** A *site* is a **home**, an
  **office**, or a **neighbourhood**; the subject type carries a built-in
  **posture** that tailors what "normal" is and what merits a human look, and
  drives every downstream step. Situational + non-accusatory by construction.
  *(`site_profile.py`, `/sites` + `/sites/postures`; `tests/test_site_profile.py`.)*
- ⬜ **Security brief — "what this means for your security".** Composes the site
  posture + the "why flagged" explainer + area context (§9) + patterns (§4) into
  a continuous, grounded, cited brief per site. LLM phrases the assembled facts,
  never invents them (same rule as the explainer). Event-gated + periodic.
- ⬜ **Suggestions to improve your security** — coverage gaps, blind spots,
  prioritised recommendations, tailored to the site posture.

### Architecture — cameras + one basic PC + our cloud *(locked)*
No camera-vendor software, no third-party NVR — only Vantage's own software runs
on the PC and in the cloud.
- **PC agent (edge):** records 24/7 to a local disk (the "past" — free) + cheap
  motion detection; uploads only motion **event** frames to the cloud. Added
  from the portal exactly like the camera Bridge (one download, auto-pairs).
- **Cloud:** runs the heavy AI (detection + Claude + the vast context) on events
  only → incidents + the site security brief. Clips pulled from the PC on demand.
- Economical because spend follows **activity**, not the clock; the vast external
  context (§9) is cached on a weekly refresh, not re-fetched per event.

## 7. Connect anything — Universal Ingest *(Phase 5)*
- 🟡 **RTSP / IP cameras**. *(`video/rtsp_reader.py`.)*
- ✅ **Auto-discover cameras on your WiFi** — multi-strategy LAN scan (ONVIF
  WS-Discovery + mDNS + multi-port sweep + RTSP OPTIONS confirmation + MAC/OUI
  vendor fingerprint), each host scored with a confidence + is-camera verdict,
  one-click add. *(`cameras/network_scanner.py`, `cameras/oui_prefixes.py`,
  `/api/cameras/scan`, console Cameras page; `tests/test_network_scanner.py`.)*
- ✅ **Scan the user's own WiFi from the cloud — "Add cameras on my network".**
  A cloud box can't see a user's LAN, so a small **Vantage Bridge** agent runs
  on that network (one personalized download, auto-pairs, connects outbound only)
  and does the discovery; the console dispatches a scan to it and shows the
  cameras. *(`cameras/bridge.py` protocol + `cameras/bridge_agent.py` +
  `/api/cameras/bridge/*` + CamerasPage bridge panel; `tests/test_camera_bridge*.py`,
  `tests/test_bridge_agent.py`.)* True one-click (signed native app, no OS
  prompt) is a later funded step.
- 🟡 **Use a phone as a camera**. *(`mobile_camera*.py`; a WebRTC/WHIP path
  — MediaMTX + coturn → RTSP, QR join — is planned but needs an infra decision:
  the box runs systemd, not docker-compose, so those services need adapting.)*
- ⬜ **Connect any other device in the house**.

## 8. Stay safe — always-on guarantees
- ✅ **Never accuses** — output is "possible / appears / needs review", never "suspect/criminal". *(`validator.py`, `tests/test_alibi_engine_validation.py`.)*
- ✅ **Human review before dispatch** — high-risk actions require a person. *(validator rules.)*
- ✅ **Auditable** — append-only logs of decisions. *(`alibi_store.py`.)*
- ✅ **Encrypted at rest**. *(`encryption.py`.)*
- ✅ **Lawful-data boundary — enforced in code, not just policy.** Vantage does
  NOT scrape or compile personal data on individuals. Defence in depth:
  `DataDomain` has no personal member (a source can't be declared for it) →
  normalisers are allowlist-based (undeclared fields dropped) → `guard.py`
  fail-closes on anything person-identifying (ID numbers, DOB, surnames,
  emails, biometrics, social profiles), rejections audited. Personal watchlist
  entries come only from lawful, consented, purpose-bound official feeds.
  *(`dataengine/guard.py`, `tests/test_dataengine.py::TestPersonalDataGuard`.)*

## 9. Ingest external data — Apify Data Engine *(Phase 6)*
> A scheduled ingestion layer (Apify actors → normalise → provenance/retention-
> tagged store) that enriches Vantage. **Scoped to lawful, non-personal data** —
> it is explicitly NOT a people-dossier database. Bright line in §8.
- ✅ **Ingestion scaffold** — Apify actor → normalise (allowlist) → personal-data
  guard → provenance/lawful-basis/retention-tagged append-only store + audit.
  Runs against fixtures with no token; with no `APIFY_TOKEN` it reports an honest
  empty result rather than inventing data. *(`dataengine/`, `tests/test_dataengine.py`.)*
- ✅ **Ingestion discipline** — every record tagged with source, lawful basis and
  retention-until (retention enforced on read *and* by `prune()`); append-only
  audit incl. every personal-data rejection; content-hash ids so re-runs don't
  duplicate; honest empty states. *(`dataengine/store.py`, `dataengine/ingest.py`.)*
- 🟡 **Places / context data** (non-personal) — sources declared
  (`places.area_crime_stats`, `places.poi`) with normalisers + lawful basis +
  retention; **needs a real Apify actor wired** (`APIFY_TOKEN` + actor id).
  Feeds the "why flagged" context (§4) and the Security Advisor (§6).
- 🟡 **Detection reference data** — sources declared
  (`reference.vehicle_models`, `reference.plate_formats`); **needs a real Apify
  actor wired**. Improves plates (§3) and make/model (§3).
- ✅ **Scheduled refresh** — weekly systemd timer re-ingests place-context for the
  areas we actually have cameras in, then prunes expired records. **Cost-bounded
  by design** (Apify bills per result): areas come only from configured cameras, a
  freshness gate skips areas already held, hard caps defer the rest (never a
  silent truncation), and `--dry-run` reports the plan spending nothing. Missing
  token → honest report, prune still runs. *(`dataengine/refresh.py`,
  `deploy/vantage-dataengine.{service,timer}`, `tests/test_dataengine_refresh.py`.)*
- ✅ **Consumer: area background on every alert** — a camera's `area` resolves to
  cited place-context shown on the incident, **structurally separate from the
  reasons**: area stats are background about a PLACE, never a reason the person
  was flagged and never attributed to them (no profiling-by-neighbourhood).
  Honest empty state when no area is set or nothing is ingested.
  *(`dataengine/context.py`, `tests/test_area_context.py::TestContextNeverBecomesAReason`.)*
- ⬜ **Consumer: Security Advisor (§6)** — feed the same context store into
  coverage/blind-spot recommendations.

---

## How to check the build is working
1. **Tests:** `pytest tests/ -q` (skips heavy-model tests when their deps are absent).
2. **Per capability:** the "Verify:" note above names the module + test for each.
3. **Live:** load the deployed app and exercise the flow (see `BUILD_PLAN.md` deploy steps). No-fake-data rule: empty states are honest, never mocked.
