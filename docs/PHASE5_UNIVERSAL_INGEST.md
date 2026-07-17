# Phase 5 — Universal Ingest (design)

> Status: **design only, nothing built.** Written 2026-07-17 at the end of the
> session that fixed the motion trigger, unified the CV stack, and cleared AGPL.
> ONVIF discovery (PR #84/#85) is done and is the first half of this phase; this
> document covers the rest.

## Why this phase is worth more than it looks

On paper Phase 5 is "connect any camera or phone". In practice it carries
something we've wanted all session for a different reason:

**go2rtc speaks WebRTC, and WebRTC fixes the live-view buffering.**

Today a live frame travels: **camera → recorder (Paul's Mac) → London → back to
Paul's browser**, which is in the same house as the recorder. We tuned it (4s
segments, ~12s of buffer) and it is now *smooth but ~12 seconds behind*. That
latency is the round trip, and no amount of tuning removes it. WebRTC lets the
browser talk **directly to the recorder over the LAN** — near-instant, and it
costs the cloud nothing.

So this phase is: ingest breadth **and** the live-view fix.

---

## 1. The blocker we already hit, and the way through

The obvious idea — "browser fetches HLS straight from the recorder's LAN IP" —
**does not work**, and it's worth writing down why so nobody retries it:

* the console is served over **HTTPS** (`vantage.developai.co.za`);
* the recorder is **HTTP on a private IP**;
* browsers **block mixed content**. A valid certificate for `192.168.3.x` is not
  practically obtainable.

**WebRTC sidesteps this entirely**, and this is the key insight of the design:

| | path | protocol |
|---|---|---|
| **Signalling** (SDP offer/answer) | browser → **cloud** → recorder | HTTPS — no mixed content, recorder stays outbound-only |
| **Media** (the actual video) | browser ↔ **recorder**, direct | ICE/DTLS-SRTP — not subject to mixed-content rules |

Signalling is small, infrequent, and already fits our outbound-poll model (the
recorder polls the cloud, exactly like `watch-requests` does today). The media
never touches the cloud when both ends are on the same LAN.

### The local-vs-remote decision — we don't make it

This was the design question I flagged as driving everything, and the answer is
that **ICE decides, not us**:

* both on the LAN → ICE picks the **host candidate** → direct, near-instant;
* remote → the host candidate fails.

We do **not** run TURN, and we do not need to:

> **WebRTC first, HLS fallback.** Try WebRTC; if ICE fails or doesn't connect
> within ~5s, fall back to the cloud HLS relay that already works today.

That gives near-instant video at home and today's behaviour away from home, with
no TURN server, no new infrastructure, and no clever detection logic. The remote
path is the thing we already built and tuned.

---

## 2. Topology

```
  camera ──RTSP──► go2rtc (on the recorder, 127.0.0.1:1984)
                     │
                     ├── WebRTC ──────────── browser (same LAN)      ← new, direct
                     ├── RTSP/snapshot ────► our ffmpeg record + motion jobs
                     └── HLS ──────────────► cloud relay ──► browser (remote)  ← today's path
```

go2rtc replaces the *live-view* ffmpeg job only. **Recording and the motion
trigger stay on our own ffmpeg jobs** — they work, they're tuned (`-c:v copy`,
`hvc1` tagging, the 0.02 scene threshold), and there is no reason to move them.

### What go2rtc buys beyond WebRTC
* One RTSP connection per camera, **restreamed** to many consumers. Today live
  view opens its own connection alongside record + motion — three per camera.
* Handles awkward cameras (H.265, odd RTSP dialects) that we've already been bitten by.
* Zero-copy passthrough where the codec allows: no transcode, no CPU.

---

## 3. The install story (a real decision, not a detail)

The recorder is deliberately **dependency-free**: a stdlib-only zipapp. It already
requires **ffmpeg** as an external binary, so a second binary is not a new
principle — but it is new friction, and the download story is the product.

go2rtc is a **single static binary**, no runtime. Options, preferred first:

1. **Recorder fetches it on first run** into its own dir, verifies a checksum,
   runs it as a child process. Keeps "download one thing and run it" true.
2. **Bundle per-platform binaries** in the download — simplest for the user,
   but bloats the `.pyz` and multiplies the build.
3. **Ask the user to install it** — rejected. We spent this whole session
   learning that every extra manual step is where onboarding dies.

**Decide before building.** Option 1 is the recommendation; the checksum is not
optional.

**Degradation is mandatory:** if go2rtc is missing or won't start, the recorder
must fall back to today's ffmpeg HLS path and say so. Live view getting *slower*
is acceptable; live view *disappearing* is not.

---

## 4. Config generation

go2rtc is configured by a YAML file listing streams. It must be **generated from
`record-targets`**, the same source the recorder already syncs:

```yaml
streams:
  dahua-192-168-3-91: rtsp://admin:***@192.168.3.91:554/cam/realmonitor?channel=1&subtype=0
  dahua-192-168-3-92: rtsp://...
api:
  listen: "127.0.0.1:1984"     # localhost only — no LAN-facing HTTP
```

* Regenerate + reload when targets change (the agent already polls for this).
* **Credentials are in this file** → `chmod 600`, in the recorder's own dir,
  never logged. Same care as `~/.vantage_bridge.json`.
* Bind the API to **127.0.0.1**. The recorder proxies; nothing else needs it.

---

## 5. Signalling flow (concrete)

Use **vanilla ICE** (wait for candidate gathering, exchange one complete SDP).
Trickle ICE is faster to connect and considerably more moving parts; our frames
are not real-time-critical to *start*.

```
1. browser  POST /api/cameras/{id}/webrtc/offer      { sdp }        → cloud stores it
2. recorder GET  /api/cameras/bridge/webrtc-requests                → picks up the offer
                 (same outbound poll as watch-requests today)
3. recorder POST http://127.0.0.1:1984/api/webrtc?src={id}  { sdp } → go2rtc answers
4. recorder POST /api/cameras/bridge/webrtc/answer   { sdp }        → cloud stores it
5. browser  GET  /api/cameras/{id}/webrtc/answer                    → sets remote description
6. media flows browser ↔ recorder directly (ICE host candidate on the LAN)
```

Notes:
* Offers are short-lived — expire them (~30s), like watch requests.
* The `/watch` heartbeat still drives whether a stream should be running at all;
  this is only the transport.
* Reuse `hls_relay`'s shape for the request store — it already does exactly this
  pattern for watch requests.

### LivePlayer changes
```
try WebRTC (5s budget)  ──connected──►  direct, near-instant
        │
        └── failed/timeout ──► existing HLS path (unchanged)
```
Show which one is live: **"Direct"** vs **"Relayed · ~12s behind"**. Users forgive
latency they understand.

---

## 6. Phone as a camera

Separate flow, same transport:

* Phone browser: `getUserMedia()` → WebRTC **publish** (WHIP) → go2rtc ingest, or
  direct to the cloud when there's no recorder on that network.
* **QR pairing:** the console shows a QR encoding a short-lived pairing URL +
  token; the phone opens it and starts publishing. No app, no typing.
* The phone stream then appears as an ordinary camera — the frame path
  (`frame_intelligence`, the scene baseline, incidents) needs **no changes**,
  which is the payoff of unifying the CV stack in PR #70.

Note the old phone endpoint (`/camera/analyze-secure`) is a *different, older*
path that still runs its own analysis. It should eventually be retired in favour
of the unified one rather than maintained in parallel.

---

## 7. Suggested order

Each step is independently useful and independently shippable:

1. **go2rtc lifecycle** — fetch, checksum, start/stop, health, fall back to ffmpeg
   if absent. No behaviour change yet; prove the process management.
2. **Config generation** from record-targets + reload on change.
3. **Live view via go2rtc HLS** — swap the existing HLS producer. Still relayed,
   but now one RTSP connection per camera instead of three. Measurable win, low risk.
4. **WebRTC signalling + direct media.** ⭐ *The prize — this is the buffering fix.*
5. **WebRTC-first / HLS-fallback in LivePlayer**, with the transport shown.
6. **Phone-as-camera + QR pairing.**
7. **ONVIF last mile** — console passes the camera login into the scan so
   discovered cameras self-configure (engine already built, PR #84/#85).

Steps 1–3 are plumbing with a real payoff. Step 4 is the one worth the phase.

---

## 8. Risks

| Risk | Mitigation |
|---|---|
| go2rtc fetch fails / wrong platform | Fall back to ffmpeg HLS, surface it in the Advisor as a real recommendation |
| WebRTC blocked (corporate/odd network) | HLS fallback — the whole reason it stays |
| RTSP credentials in the go2rtc config | `chmod 600`, localhost-only API, never logged |
| A second binary makes the recorder heavier | Measure. The 3→1 RTSP connection saving may well pay for it |
| Two live-view paths to maintain | Accept deliberately: remote genuinely needs a relay. Don't build a third |

## 9. What "done" looks like

* At home, live view is **near-instant** and the console says **Direct**.
* Away from home, it still works, visibly **Relayed**.
* Adding a camera means: scan → pick → it plays. No RTSP path typed.
* A phone becomes a camera by scanning a QR code.
* go2rtc absent → everything still works, slower, and the Advisor says why.

## 10. Test it against reality

The lesson of the session that preceded this: **every real bug came from real
frames**, and none were visible from the layer below. So:

* Test against **Paul's actual cameras**, not a sample image.
* WebRTC either connects or it doesn't — but *why* it fell back must be logged.
  A silent fallback would hide exactly the failure this phase exists to fix, and
  would look identical to success.
* Never ask Paul to walk in front of a camera to test — see the memory note.
  Inject a frame server-side, or wait for natural motion.
