# Vehicle intel, patterns, disk & human-source data — slimmed plan

> Status: **plan, nothing built from this doc yet.** Scoped to the *actual*
> repo (D-FINE detection, FastALPR plates, VLM+catalog make/model, ReID
> cross-camera, dataengine ingest — no Frigate, no Ultralytics). Every item
> below says what already exists so we extend rather than rebuild, and holds
> the house rules: **real data or honest empty states, never mock; VLM-or-
> absent for attributes; never accuse; identity only from the owner.**

The four asks, in build order (cheapest-real-value first):

---

## 1. Make/model review queue + local-data loop *(genuinely new)*

**The gap.** `vehicle_attrs._classify_make_model()` is still a `PLACEHOLDER`
stub returning `"unknown"`. Make/model today comes from the VLM, validated
against the curated SA catalog (`dataengine/vehicle_reference.py` downgrades
unknown badges). There is **no loop that turns the platform's own footage into
local training data** — the thing that would eventually let a cheap local
classifier replace paid VLM calls, and the plan's one strongest point (US/EU
make-model models misfire on the SA vehicle mix).

**Build.**
- `vehicles/review_queue.py` — append every vehicle crop that earned an
  attribute guess, with: frame_id + bbox (the crop is a view of a frame we
  already hold — no new storage, same trick as the people strip), the VLM's
  claimed colour/make/model/body + confidence, the plate region if read, and
  a `label` field (empty until a human confirms). Amber path: **low-confidence
  or catalog-downgraded guesses land here for review**; high-confidence ones
  are auto-accepted but still logged so the training set has positives too.
- A **Vehicle review page** (or a tab on the existing Vehicles page): each row
  is the crop + the guess + a one-click confirm / correct (pick make+model
  from the catalog, or "not a vehicle"). Corrections are the gold labels.
- `vehicles/local_dataset.py` — export confirmed rows as an image-crop +
  label manifest (crops rendered from the stored frames on demand, never a
  second copy at rest). This is the corpus a local classifier trains on later.
- **Honesty:** the queue never changes what the client SEES — the Overview
  still shows VLM-or-absent. The queue is a back-office training surface only.

**Explicitly deferred:** training/serving a local make/model model. This phase
only *builds the labelled dataset* — sizing a classifier onto the 4 GB box is
its own decision (box first). Ship the loop; harvest labels while we decide.

---

## 2. Active pattern: "how often has this vehicle been seen" *(mostly exists — extend)*

**What exists.** `cross_camera.entity_summary("vehicle", hours=N)` already
returns, per appearance-ReID vehicle cluster: `count`, `first_seen`,
`last_seen`, `days`, `active_hours`, and a 24-bucket hour histogram.
`get_entity_trail()` returns the full chronological sighting list. The Overview
already shows `recurring_vehicles` + `pattern_findings` ("Vehicle A is here all
the time / NEW to the scene") and the owner can name a cluster.

**The gap.** No **per-vehicle history view** you can open, and the window is
fixed at the range toggle. "How often over a period" is computed but not
*explorable*.

**Build.**
- `GET /patterns/vehicle/{entity_id}?window=…` → the cluster's trail: every
  sighting (time, camera, crop), the count, a per-day and per-hour breakdown,
  its familiarity class (resident/regular/new), and the owner label if set.
  Thin wrapper over `entity_summary` + `get_entity_trail` — the engine is done.
- **Overview → click a recurring vehicle → its history panel** (modal, like the
  People history panel already there): "Seen 41× over 6 days — mostly 07:00 and
  17:00 (school-run rhythm). First seen Tue 14:02, last 8m ago. Registered in
  Cape Town (local)." Sparkline of sightings-per-day.
- Add a **window selector** (24h / 7d / 30d) to the vehicle history so "over a
  certain period" is the owner's choice, not a fixed range.
- **Honesty:** continuity, never identity — it's an appearance cluster from our
  own cameras, labelled by the owner or anonymous ("Vehicle A"). Same line the
  people strip holds.

---

## 3. Conserve recorder disk *(retention EXISTS — make it actually bind)*

**What exists.** `cameras/recorder.py` already has a full, tested retention
system: `plan_retention(files, now, RetentionPolicy(max_bytes, max_age_seconds))`
— age cap first, then oldest-first byte-budget sweep, pure and unit-tested.

**The real problem.** It's not being *applied effectively* on Paul's recorder —
the disk is filling, so either no policy is set, the caps are too high, or the
sweep isn't running on the agent. This is **wiring + defaults + visibility**,
not new machinery.

**Build.**
- **Sensible default policy in the record-agent**: a per-camera byte budget
  (e.g. default 20 GB/camera) AND an age cap (e.g. 14 days), whichever hits
  first — applied out of the box so a fresh recorder never runs the disk dry.
- **Free-space floor**: also stop/sweep when the *disk itself* drops below a
  headroom threshold (e.g. keep 10 % free), independent of per-camera budgets —
  the safety net that directly answers "it's wiping out my HD".
- **Portal control + readout**: surface the policy on the Recorders page
  (budget GB/camera, age cap, current disk used/free per recorder) so it's set
  and visible, not buried in agent config. The agent already reports home;
  add disk stats to that heartbeat.
- **Verify the sweep runs**: the agent must invoke `plan_retention` on a timer
  and actually delete — confirm end-to-end on the real recorder (the sweep is
  pure; the deletion wiring is what to check).
- **Lower-res sub-stream option** for the continuous record where evidence
  quality allows — the biggest single byte saver. Already have MAIN/SUB URL
  resolution; expose "record SUB stream" per camera.
- **Honesty:** deletion is oldest-first and logged; motion-flagged clips can be
  given a longer age cap so evidence isn't swept while idle footage is.

---

## 4. Human-source data (guards / people) fitting the camera data *(new)*

**What exists (and what it is NOT).** `dataengine/user_sources.py` lets the
owner declare *web-scrape* sources (domains, lawful basis). That is **not** what
this asks for. This is **field reports from people** — a guard logging "white
bakkie, no plate, parked at the north gate ~02:00, left after 20 min" — as a
first-class data source alongside the cameras.

**Build.**
- `reports/field_reports.py` — a store for human observations, each:
  `{ts, observer (name/role), camera_or_location, subject (person|vehicle|
  other), free_text, structured tags (colour, vehicle type, direction), photo?
  optional}`. Append-only, encrypted at rest like the other stores.
- **Submit surfaces**: a simple "Log a report" form in the console (guard/
  operator role), and — because guards are on their phones — a **tokenised
  mobile submit link** per site (reuse the bridge-pairing pattern) so a guard
  submits without a full login. Rate-limited, audited.
- **Fit it to the camera data**: a report tagged to a camera + time window is
  shown *next to* that window's sightings — "Guard report 02:04: white bakkie,
  north gate" sits beside the vehicle sightings from 02:00–02:20. Where a report
  names a plate/colour that matches a real sighting, link them (a corroboration,
  never an accusation).
- **Overview surface**: a **"Reports from the ground" panel** — recent human
  observations, newest first, each with observer + time + camera, and a badge
  when one corroborates a camera sighting. Honest empty state until someone
  files one.
- **Honesty / POPIA:** these are observations by identified people about what
  they saw, kept as evidence and phrased situationally — the same non-accusatory
  validator applies; a report is "worth a look", never a verdict. No compiling
  personal dossiers; a report about a named person is still just one logged
  observation, not a profile.

---

## Order & why

1. **Disk (#3)** first — it's actively hurting Paul now and is mostly wiring +
   defaults. Fastest real relief.
2. **Vehicle history (#2)** — the engine's built; this is an endpoint + a panel.
   High visible value, low risk.
3. **Field reports (#4)** — new store + form + Overview panel; the richer-
   dataset ask, self-contained.
4. **Review queue (#1)** — new, and the longest game (it pays off only once a
   local classifier is trained), so it comes last but starts *harvesting labels*
   immediately so the corpus grows while everything else ships.

Every phase is one PR-sized slice, verified against the real cameras/recorder
before the next — the same discipline the rest of the repo already runs on.

## Not in this plan (deferred, on purpose)

- Training/serving a local make/model classifier (needs box sizing).
- Any Frigate ingest — not our camera layer; revisit only if a real client runs it.
- Cross-client linking, autonomous "this car is suspicious" alerting — V1 reads,
  classifies, matches, logs; a human interprets.
