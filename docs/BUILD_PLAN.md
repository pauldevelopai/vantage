# Vantage / SMARTGUARD — Build Plan

> The AI intelligence layer for cameras that prevents crime and helps people
> and police act on what their cameras see. Concept note: `guard.pptx`.

**Positioning note (2026-07):** the original concept is police/CCTV. The newer
feature requests ("your wifi", "in your house", "any phone camera", "improve
*your* security") add a **home / consumer / SME** dimension. Much of the engine
is shared, but the UX, onboarding, and trust model differ between "police
control room" and "homeowner with a phone." Decide whether Vantage is one
product with two doors (like BE AI READY / GROUNDED) or two products.

---

## Phase 1 — Foundation ✅ DONE
Make the existing pillars actually work (they were broken/placeholder).
- **Digital Watchlist** — ArcFace recognition + SCRFD detection (PR #3, merged).
- **Vehicle Intelligence** — colour-aware plate mismatch (PR #4, merged).
- **Control Room** — console build fixed (`auth.ts`/`sse.ts`) + served (PR #5).

---

## Phase 2 — Pattern Detection & History  *(the concept's differentiator)*
"Tell me who and what has been happening" + "have these people/plates been
involved before." Builds directly on Phase 1's ArcFace embeddings + ReID.

| Requested feature | Have today | Gap to build |
|---|---|---|
| **Patterns over last hour / 24h / week** | `cross_camera` trails, `metrics.compute_summary(range)`, incident + analysis stores | A **time-windowed activity/pattern engine**: who/what/where per window, co-occurrence ("this vehicle near 3 incidents"), hotspot + time-of-day clustering, a readable narrative summary |
| **Number-plate matches** | FastALPR + hotlist store + detector (built) | Surface matches in the pattern/Control-Room view; link a plate to its full sighting trail |
| **People involved in anything before** | `face_sighting_store` (logs every face), ArcFace embeddings (Phase 1), watchlist, incident history | **Person-history lookup**: given a detected face embedding, find prior sightings/incidents across the archive (cosine search over the sighting store) + a "seen before / linked to incident X" verdict |
| **"Why flagged" explainer** | validator rationale, `alibi.context` fusion | A grounded, cited explanation on every alert — human-in-the-loop, never an accusation |

**Key tasks:** a `patterns/` module (windowed aggregation + co-occurrence +
clustering); vector search over `face_sighting_store` / vehicle sightings;
person- and plate-centric timeline views in the console.

---

## Phase 3 — Behaviour & Threat Detection
"Detect suspicious behaviour vs. just walking, and guess if a person is armed."

| Requested feature | Have today | Gap to build |
|---|---|---|
| **Suspicious behaviour vs. normal** | tracking (loitering / dwell time), motion history | **Behaviour classification** — pose/action model (running, fighting, loitering, following) over tracks; anomaly scoring vs. a learned "normal" baseline (`activity_baseline` exists as a seed) |
| **Armed / weapon guess** | gatekeeper checks knife/gun object classes crudely | A real **weapon detector** (object model fine-tuned on firearms/knives) + a calibrated, cautious "possibly armed" signal — high-stakes, so conservative thresholds + mandatory human review |

**Key tasks:** integrate a pose/action recogniser on tracks; a weapon-detection
model (its own onnxruntime model, like D-FINE/ArcFace); wire both into the
threat assessment with the existing "never accuse" safety rules.

> ⚠️ "Guess if armed" is the highest-liability feature in the product. It must
> be framed as *possible*, always require human confirmation, and be logged —
> consistent with the No-Accuse / human-in-the-loop rules already enforced.

---

## Phase 4 — Security Advisor
"Give suggestions on how to improve your security."

- **Have today:** `continuous_learning` threat enhancement; BE AI READY's
  advisory/recommendations pattern to borrow from.
- **Gap:** a **security advisor** that reviews the site's cameras, coverage
  gaps, incident history and blind spots, and produces prioritised, plain-
  English recommendations ("camera 3 has a 40-min nightly blind spot",
  "no coverage on the north gate", "enable plate hotlist"). Cited, honest,
  no fabricated data.

---

## Phase 5 — Universal Ingest  *(the "any camera, any device" story)*
"Lock onto any cameras on your wifi" + "connect any phone camera or any other
device in your house."

| Requested feature | Have today | Gap to build |
|---|---|---|
| **Auto-discover WiFi cameras** | `cameras/network_scanner.py`, `vms_connect.py` (partial) | Robust **ONVIF/RTSP LAN discovery** + one-click connect; go2rtc for reliable multi-camera ingest |
| **Connect any phone / home device** | `mobile_camera` (phone-as-camera), `rtsp_reader` | Easy **phone-as-camera pairing** (WebRTC ingest, QR pairing), and generic device/RTSP/ONVIF onboarding |

**Key tasks:** a discovery/onboarding service (scan → identify → connect);
WebRTC/go2rtc ingest; a "add a camera / add my phone" flow in the UI.

---

## Phase 6 — Field + On-prem (from the original plan)
- Officer mobile "scan → instant verdict"; field auth.
- On-premise deployment profile ("data stays under your control").
- Full RBAC / audit / encryption hardening.

---

## Cross-cutting
- **No fake data** — real detections or honest empty states, never mocks.
- **Human-in-the-loop / No-Accuse** — every high-risk signal is "possible",
  requires review, and is audit-logged.
- **Licensing** — keep detection AGPL-free (D-FINE); tracking still on
  ultralytics → standalone ByteTrack to finish clearing AGPL.
- **Box footprint** — surepath is 4 GB/2 vCPU; each new model competes for RAM.
  Phases 3–5 likely need a bigger box or model-tiering.
