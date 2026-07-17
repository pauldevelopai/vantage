# Overview at a glance — people, cars, and what we watch for (design)

> Status: **design only, nothing built.** Agreed with Paul 2026-07-17.
> The Overview tab is what gets shown to clients, so this is what it must answer
> in one look: **which cars have been here (shot + make/model + plate + time),
> which people (shot + who, honestly), and what we're watching for (and whether
> it fired).**

## The rule this design is built around

Everything below shows **real data or an honest empty state**. Three specific
temptations to refuse, because each is a way this design could quietly become a lie:

1. **Never invent a make/model.** The current classifier is a stub —
   `_classify_make_model()` returns `"unknown", "unknown", 0.0` with a
   `PLACEHOLDER` docstring, and every `VehicleSighting` is written
   `make="unknown", model="unknown"`. Attributes come from the VLM or they are absent.
2. **Never guess a stranger's identity.** See §3. This is the POPIA line and it
   is not negotiable.
3. **Never call anything a crime.** See §4.

---

## 1. Snapshots without storing new images

We already store the **evidence frame** per event (`/api/cameras/frames/{id}.jpg`)
and the **bbox** of every face (`FaceSighting.bbox`) and detection
(`intel.detections[].bbox`). So a face shot or car shot is a **crop of a frame we
already have** — no second pipeline, no extra storage, no new privacy surface.

Do it **client-side**: extend `AuthImg` (or wrap it) to take an optional bbox and
render the crop with CSS transforms:

```
<CropImg src="/api/cameras/frames/ab12.jpg" bbox={[x, y, w, h]} pad={0.35} />
   → a container with overflow:hidden and an <img> scaled/translated so the bbox
     fills it. `pad` widens the box (a face crop needs headroom to read as a face).
```

Why client-side: the frame is already fetched and authenticated, cropping is free,
and the full frame stays one click away. **Bboxes are in the frame's pixel space** —
so the crop needs the frame's natural dimensions; read them from the loaded image
rather than assuming the camera's resolution (the motion job scales frames to
`min(iw,640)`, so bbox space and camera space are **not** the same).

> ⚠️ Verify this before building: confirm bboxes are in the **stored frame's**
> coordinates, not the pre-scale source. If they don't line up, crops will be
> subtly wrong in a way that looks like a rendering bug. Test against a real frame
> with a known person in it.

---

## 2. Cars at a glance

A strip of recent vehicles, each: **the car's crop**, its attributes, plate, time,
camera.

```
┌──────────┐  White SUV · Toyota Fortuner
│  [crop]  │  CA 123-456          ← only if actually read
└──────────┘  Driveway · 07:42
```

### Where each field really comes from
| Field | Source | Status |
|---|---|---|
| shot | crop of the evidence frame via detection bbox | ✅ have |
| plate | YOLO-v9 LPD + OCR → `intel.plates[]` | ✅ built (none read yet — cameras face garden/driveway, not road) |
| time / camera | the event | ✅ have |
| colour | `vehicle_attrs._classify_color` (HSV) | ✅ exists, currently unused by the frame path |
| **make / model** | **the VLM** — see below | ⬜ to build |

### Make/model: ask Claude, don't fake it
Claude already writes *"a **white SUV with roof rails** is parked on a cobblestone
driveway"* unprompted. It can see this. So on frames where the detector found a
vehicle, ask for **structured** attributes alongside the description:

```json
{"vehicles": [{"colour": "white", "make": "Toyota", "model": "Fortuner",
               "body": "SUV", "confidence": "high|medium|low"}]}
```

Rules:
* **Only on frames that already earn a VLM call** (the cost gate: person/vehicle
  detected, or a hotlist/watchlist hit). This adds no extra spend.
* Persist onto `VehicleSighting.make/model/color` — the fields exist and are
  currently dead.
* **Show confidence honestly.** `"White SUV"` when it's sure of the body but not
  the badge; never a model it guessed. A wrong make in front of a client is worse
  than no make.
* This is a **VLM opinion about an image**, not a registry lookup. Label it as
  observed, and never let it flow into anything that reads as a record.

---

## 3. People at a glance

Same shape — face crop, then who, honestly:

```
┌──────────┐  Paul McNally            ← enrolled: a real name
│  [face]  │  Front Gate · 07:41
└──────────┘

┌──────────┐  Unknown person
│  [face]  │  seen 4× since Tue · first Front Gate 19:12
└──────────┘  [ Add to Faces ]
```

### The boundary, restated because this is where it would erode
* **Enrolled → named.** ArcFace match against people *the owner enrolled*. Real,
  lawful, and it's identification the owner can defend.
* **Stranger → continuity, never identity.** *"Seen 4× since Tuesday"* — from
  `person_history` (cosine search over our **own** sightings). We never guess who
  an unknown person is. That's the Clearview line and the thing that would end
  this product in SA.
* Continuity also **demos better**: "this person has been here four times this
  week" survives *"how do you know?"*. A guessed name does not.

### Faces page (renamed from Watchlist)
This is what makes §3 get better with use:
* **Rename Watchlist → Faces** (route, nav, page). "Watchlist" reads as
  law-enforcement; "Faces" reads as *the people who belong here*.
* **One-click enrol from an unknown face** on the Overview — the crop is already
  there, so enrolling is a name and a button. Every enrolment makes the next
  sighting say a name instead of "unknown".
* Show each enrolled person with their face, when last seen, and how often.
* Keep the existing enrol-by-upload for people not yet caught on camera.

The watchlist gets strong by **use**, not by import — which is the lawful path and
also the only one that works.

---

## 4. What this site watches for

Not "crimes". We do not detect crimes and must never claim to — but the honest
version already exists and is unused.

Every `SiteProfile` posture defines `review_triggers`. For a home:
* presence at the perimeter outside normal hours
* extended dwell at an entry point without approaching the door
* repeated passes of the property in a short window
* an unfamiliar vehicle stationary at the boundary for an extended period

Show them as an **armed panel**, each with state:

```
WATCHING FOR                                    (home · My House)
● After-hours presence at the perimeter    ✓ 19:42 Front Gate  →
● Dwell at an entry point                    not seen
● Repeated passes in a short window          not seen
● Unfamiliar vehicle at the boundary         not seen
```

* Reads as capability even when nothing has fired — which is most of the time,
  and is the point.
* A fired trigger links to its incident.
* Language stays situational: *"worth a look"*, never *"intruder"*. The validator
  already enforces this; do not route around it.

**Gap to build:** the triggers are currently descriptive text in the posture, not
evaluated conditions. Each needs a real evaluator over stored events (after-hours
= event outside `normal_hours`; dwell = a track's `stationary_duration`; repeated
passes = N events for the same ReID within a window). Until a trigger has an
evaluator, show it as **armed but not yet evaluated** — do not imply we checked
and found nothing.

---

## 5. Endpoints

Prefer extending `GET /dashboard/overview` — it already assembles the Overview
from real events in one call, and adding sections keeps it one round trip:

```
recent_vehicles: [{ frame_url, bbox, colour, make, model, body, attr_confidence,
                    plate, camera_name, ts, event_id }]
recent_people:   [{ frame_url, bbox, matched_label|null, sighting_id,
                    times_seen, first_seen, camera_name, ts }]
watching_for:    [{ trigger, evaluated: bool, fired: bool, ts|null,
                    camera_name|null, incident_id|null }]
```

`times_seen` per face means a person-history lookup per row — **cache it or bound
it**, or a busy window turns the Overview into N cosine searches.

## 6. Order

1. `CropImg` + verify bbox↔frame coordinate space against a real frame. *Everything
   else depends on this being right.*
2. **People strip** — face crops + enrolled names + continuity. All the data exists.
3. **Faces page** rename + one-click enrol from the Overview. Makes §2 compound.
4. **VLM vehicle attributes** → persist to `VehicleSighting` → **Vehicles strip**.
5. **Watching-for panel** — start with the two triggers that have honest
   evaluators (after-hours presence, dwell); show the rest as armed-not-evaluated.

Steps 1–3 need no new AI. Step 4 costs nothing extra (rides the existing gate).

## 7. Test it against reality

Per [[vantage-real-frames-find-real-bugs]]: test against Paul's real cameras, not
a sample image. Specifically —
* crops must be checked against a **real frame with a real person**, or they'll be
  subtly misaligned in a way that looks like a CSS bug;
* if the VLM returns a make it isn't sure of, that must render as *"White SUV"*,
  not *"Toyota Fortuner"*. Verify with a real car;
* never ask Paul to stand in front of a camera — inject server-side or wait for
  natural motion.
