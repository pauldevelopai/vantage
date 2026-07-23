// Alibi Console Types

export interface IncidentSummary {
  incident_id: string;
  status: string;
  created_ts: string;
  updated_ts: string;
  event_count: number;
  max_severity: number;
  avg_confidence: number;
  recommended_action?: string;
  requires_approval?: boolean;
  camera_id?: string;
  zone_id?: string;
  event_type?: string;
}

export interface CameraEvent {
  event_id: string;
  camera_id: string;
  ts: string;
  zone_id: string;
  event_type: string;
  confidence: number;
  severity: number;
  clip_url?: string;
  snapshot_url?: string;
  metadata: Record<string, any>;
}

export interface IncidentDetail {
  incident_id: string;
  status: string;
  created_ts: string;
  updated_ts: string;
  events: CameraEvent[];
  plan?: {
    summary: string;
    severity: number;
    confidence: number;
    uncertainty_notes: string;
    recommended_next_step: string;
    requires_human_approval: boolean;
    action_risk_flags: string[];
    evidence_refs: string[];
  };
  alert?: {
    title: string;
    body: string;
    operator_actions: string[];
    evidence_refs: string[];
    disclaimer: string;
  };
  validation?: {
    status: string;
    passed: boolean;
    violations: string[];
    warnings: string[];
  };
}

export interface ExplanationReason {
  factor: string;
  detail: string;
  citation: Record<string, unknown>;
}

export interface ContextItem {
  kind: string;
  detail: string;
  citation: Record<string, unknown>;
}

/** Area background (§9) — about the PLACE only. Never a reason for the flag,
 *  never attributed to the detected individual. */
export interface AreaContext {
  area: string;
  items: ContextItem[];
  rule: string;
}

export interface IncidentExplanation {
  incident_id: string;
  rationale: string;
  reasons: ExplanationReason[];
  method: 'claude' | 'ollama' | 'openai' | 'template';
  grounded: boolean;
  disclaimer: string;
  area_context?: AreaContext | null;
}

export interface DecisionRequest {
  action_taken: string;
  operator_notes: string;
  was_true_positive: boolean;
  dismiss_reason?: string;
  /** The human's own words for what happened when confirming ("attempted
   *  break-in"). Shown on the Overview attributed to them — the system itself
   *  never declares a crime. */
  label?: string;
}

export interface Settings {
  incident_grouping: {
    merge_window_seconds: number;
    dedup_window_seconds: number;
    compatible_event_types: Record<string, string[]>;
  };
  thresholds: {
    min_confidence_for_notify: number;
    high_severity_threshold: number;
  };
  api: {
    port: number;
    host: string;
  };
}

export interface ShiftReport {
  start_ts: string;
  end_ts: string;
  incidents_summary: string;
  total_incidents: number;
  by_severity: Record<number, number>;
  by_action: Record<string, number>;
  false_positive_count: number;
  false_positive_notes: string;
  narrative: string;
  kpis: Record<string, any>;
}

export interface SSEEvent {
  type: 'heartbeat' | 'incident_upsert';
  timestamp?: string;
  incident_summary?: IncidentSummary;
}

export interface Camera {
  camera_id: string;
  name: string;
  source: string;
  source_type: string;
  enabled: boolean;
  location: string;
  /** Suburb/area — links this camera to place-context (§9). Empty = no context. */
  area: string;
  status: string;
  last_seen: string | null;
  vms_config: Record<string, any>;

  /** Whether anything is actually watching this camera right now — NOT the same
   *  as "a picture arrived recently". Frames are only sent when something
   *  changes, so a working camera on a still driveway is quiet, not dead.
   *  See alibi/cameras/liveness.py. */
  watching?: boolean;
  state?: 'live' | 'quiet' | 'stopped' | 'never';
  label?: string;
  detail?: string;
  /** The recorder or handset feeding it. */
  feeder?: string | null;
  feeder_online?: boolean;
}

export interface TrailEntry {
  camera_id: string;
  timestamp: string;
  metadata: Record<string, any>;
}

/** API credit balance & runout — the balance is ENTERED by the owner (Anthropic
 *  has no balance API); spend/burn/runout are measured from tracked usage.
 *  All-null balance fields = not entered yet; the page prompts, never invents. */
export interface CreditStatus {
  balance_usd: number | null;
  set_at: string | null;
  set_by: string | null;
  spent_since_usd: number | null;
  remaining_usd: number | null;
  daily_burn_usd: number | null;
  days_left: number | null;
  runout_date: string | null;
}

/** Service usage & estimated cost. */
export interface CostSummary {
  currency: string;
  window_days: number;
  total_usd: number;
  by_service: Record<string, { calls: number; input_tokens: number; output_tokens: number; usd: number }>;
  by_day: Array<{ day: string; usd: number; calls: number }>;
  credits: CreditStatus;
  note: string;
}

/** The subject a Vantage deployment protects. */
export type SubjectType = 'home' | 'office' | 'neighbourhood';

/** How the intelligence layer is tuned for a subject type (from the backend). */
export interface Posture {
  subject_type: SubjectType;
  label: string;
  summary: string;
  focus: string[];
  normal: string[];
  review_triggers: string[];
  brief_sections: string[];
}

/** A protected site + its built-in intelligence posture. */
export interface Site {
  site_id: string;
  name: string;
  subject_type: SubjectType;
  area: string;
  address: string;
  timezone: string;
  normal_hours: Record<string, any>;
  camera_ids: string[];
  notes: string;
  context: string;
  created_at: string;
  updated_at: string;
  posture: Posture;
}

// --- Dashboard overview (all real, from stored camera events) --------------- //

export interface DashboardRow {
  event_id: string;
  camera_id: string;
  camera_name: string;
  ts: string;
  event_type: string;
  severity: number;
  confidence: number;
  snapshot_url?: string;
  description: string;
  people: number;
  vehicles: number;
  plates: string[];
  watchlist_hit: boolean;
  watchlist_label?: string | null;
  hotlist_hit: boolean;
  hotlist_reason?: string | null;
  who?: string | null;           // a recognised person, so the card isn't just "Person"
}

export interface DashboardCamera {
  camera_id: string;
  name: string;
  latest?: DashboardRow | null;
}

/** One tile on the Overview people strip. Enrolled → matched_label is the real
 *  name; a stranger has matched_label null and continuity fields instead — the
 *  UI must never present a guessed identity. */
export interface DashboardPerson {
  sighting_id: string | null;        // null for detection-only rows (no face)
  source: 'face' | 'detection';
  frame_url: string;
  bbox: number[];                    // [x, y, w, h] in the stored frame's pixels
  camera_id: string;
  camera_name: string;
  ts: string;
  matched_label: string | null;
  matched_person_id?: string | null; // the enrolled person, when recognised — deep-links to their page
  times_seen: number;                // 0 for detection-only rows (no embedding to link)
  first_seen: string | null;
  incident_id?: string | null;       // the incident this sighting belongs to (click-through)
}

/** One tile on the Overview vehicles strip. Attributes are the VLM's opinion of
 *  the image (or absent) — make/model must only be shown at high confidence;
 *  a wrong badge in front of a client is worse than no badge. */
export interface DashboardVehicle {
  event_id: string;
  frame_url: string;
  bbox: number[];                    // [x, y, w, h] in the stored frame's pixels
  colour: string | null;
  make: string | null;
  model: string | null;
  body: string | null;
  attr_confidence: 'high' | 'medium' | 'low' | null;
  /** Free D-FINE class (car/truck/bus/motorcycle) — a real coarse type even
   *  when the VLM didn't run to give a body/make/model. */
  det_class: string | null;
  plate: string | null;
  /** Where the vehicle is REGISTERED (from the plate) — never where a person
   *  is from. Present only when the plate could be placed with confidence. */
  region: PlateRegion | null;
  incident_id?: string | null;       // the incident this vehicle sighting belongs to
  camera_id: string;
  camera_name: string;
  ts: string;
}

export interface PlateRegion {
  plate: string;
  province: string;
  town: string | null;
  confidence: 'high' | 'medium' | 'low';
  out_of_area: boolean;
  text: string;
  basis: string | null;
}

/** One posture trigger on the watching-for panel. evaluated=false means armed
 *  but not yet checked — the UI must say so, never "not seen". */
export interface WatchingForTrigger {
  trigger: string;
  kind: string | null;
  evaluated: boolean;
  fired: boolean;
  ts?: string;
  camera_id?: string;
  camera_name?: string;
  event_id?: string;
  sighting_id?: string;
  note?: string;
}

export interface WatchingFor {
  site_id: string;
  site_name: string;
  subject_type: string;
  posture_label: string;
  triggers: WatchingForTrigger[];
}

export interface DashboardOverview {
  range: string;
  generated_at: string;
  kpis: { events: number; alerts: number; people: number; vehicles: number; vehicles_distinct: number | null };
  by_type: Array<{ type: string; count: number }>;
  over_time: Array<{ hour: string; events: number; alerts: number }>;
  recent: DashboardRow[];
  cameras: DashboardCamera[];
  alerts: DashboardRow[];
  recent_people: DashboardPerson[];
  recent_vehicles: DashboardVehicle[];
  suspicious_vehicles?: (DashboardVehicle & { reason?: string })[];
  watching_for: WatchingFor | null;
  patterns: DashboardPatterns | null;
  situations: DashboardSituation[];
  known_people?: KnownPerson[];
  alerts_total?: number;              // how many alert candidates there were (top 10 shown)
  out_of_ordinary_vehicles?: OutOfOrdinaryVehicle[];
  named_vehicles?: NamedVehicle[];
  recurring_vehicles: RecurringVehicle[];
  pattern_findings: PatternFinding[];
  security_suggestions: SecuritySuggestion[];
  field_reports?: FieldReport[];
}

/** A human observation from the ground (guard/operator) — evidence beside the
 *  cameras, never a verdict. corroboration is a camera sighting that backs it. */
export interface FieldReport {
  report_id: string;
  ts: string;
  observer: string;
  subject: 'person' | 'vehicle' | 'other';
  note: string;
  camera_id: string | null;
  camera_name?: string | null;
  location: string;
  tags: Record<string, string>;
  source: string;
  corroboration?: { event_id: string; ts: string; colour: string | null; camera_name: string | null } | null;
}

/** An appearance-ReID cluster: the SAME vehicle seen repeatedly, linked by our
 *  own cameras' embeddings. Anonymous ("Vehicle A") — continuity, no identity. */
export interface RecurringVehicle {
  label: string;                     // descriptor ("White SUV") or "Unnamed vehicle"
  descriptor?: string | null;        // colour+type when known, else null (photo carries it)
  entity_id: string;
  owner_label: string | null;        // the owner's own name for it ("Paul's Fortuner")
  familiarity: 'resident' | 'regular' | 'new' | 'occasional';
  count: number;
  days: number;
  first_seen: string;
  last_seen: string;
  cameras: string[];
  busiest_hour_utc: number | null;
  frame_url?: string | null;         // a real photo of the actual car
  bbox?: number[] | null;            // its box in that frame (for a client-side crop)
  colour?: string | null;
  body?: string | null;
  plate?: string | null;             // most-read plate (the stable identity), or null
  plate_region?: string | null;
  /** Distinct visits, not frames. A parked car is detected in every
   *  frame it sits in — that is how this read "seen 4368x". */
  passes?: number | null;
}

/** One row on the Overview's Situations panel — the top things worth a look,
 *  against our criteria. May be a raised incident OR a criteria signal (a new
 *  vehicle, presence after hours, someone at the parked cars). The machine's
 *  ceiling is tier "review" — "confirmed" (and any crime word in its label)
 *  only ever comes from a person, whose name is attached. */
export interface KnownPerson {
  person_id: string;
  name: string;
  details?: string | null;
  times_seen: number;
  cameras: string[];
  busiest_hour: number | null;
  last_seen: string | null;
  first_seen: string | null;
  views_on_file: number;
}

export interface DashboardSituation {
  incident_id: string | null;         // present for incidents; null for criteria rows
  kind?: 'confirmed' | 'review' | 'noted' | 'after_hours' | 'at_vehicles'
       | 'repeated_passes' | 'dwell' | 'new_vehicle';
  entity_id?: string | null;          // vehicle-history click-through (new_vehicle rows)
  event_id?: string | null;
  count?: number | null;              // e.g. how many vehicles someone was near
  tier: 'confirmed' | 'review' | 'noted';
  status?: string;
  severity?: number;
  ts: string;
  camera_id?: string | null;
  camera_name: string | null;
  title: string | null;
  event_type?: string | null;
  description: string;
  snapshot_url: string | null;
  frame_url?: string | null;          // vehicle situations: photo of the car (crop with bbox)
  bbox?: number[] | null;
  plate?: string | null;
  confirmed: { by: string; ts: string; label: string | null; notes?: string } | null;
  /** An enrolled person recognised in this frame. Never a guess — an
   *  unrecognised face leaves this null and the card stays generic. */
  who?: string | null;
  /** 1-based position in the ranked top ten (1 = most important). */
  rank?: number;
  importance?: number;
  why?: string[];   // short reasons this ranked where it did
  watchlist_hit?: boolean;
  hotlist_hit?: boolean;
  owner_label?: string | null;   // a named vehicle's owner label
}

/** A vehicle the owner has named — the persistent "known vehicles" database.
 *  Stays listed even when not seen recently or nothing is recording. */
export interface NamedVehicle {
  entity_id: string;
  label: string;
  plate?: string | null;
  plate_region?: string | null;
  frame_url?: string | null;
  bbox?: number[] | null;
  last_seen?: string | null;
  count?: number | null;
  cameras: string[];
  seen_recently: boolean;
  /** Distinct visits, not frames. A parked car is detected in every
   *  frame it sits in — that is how this read "seen 4368x". */
  passes?: number | null;
}

/** A car that is NOT the usual scene — new or occasional, unnamed — with how
 *  often it came down the road (distinct VISITS, not motion-stills) and when
 *  (busiest local hour). The usual cars (residents, regulars, owner-named) are
 *  excluded by definition. */
export interface OutOfOrdinaryVehicle {
  entity_id: string;
  familiarity: 'new' | 'occasional';
  descriptor?: string | null;  // colour+type when known ("White SUV"), else null
  passes: number | null;       // distinct visits — the honest "how often"
  /** An enrolled person recognised in the frame. Never a guess — an
   *  unrecognised face stays generic. */
  who?: string | null;
  sightings: number;           // raw motion-stills (not shown as passes)
  days: number;
  first_seen: string;
  last_seen: string;
  busiest_hour_local: number | null;
  cameras: string[];
  frame_url?: string | null;   // a real photo of the actual car
  bbox?: number[] | null;      // its box in that frame (for a client-side crop)
  plate?: string | null;       // most-read plate, or null
  plate_region?: string | null;
}

/** Hour-of-day activity per camera (site-local time) — all from real events. */
export interface DashboardPatterns {
  tz: string;
  by_camera_hour: Array<{ camera_id: string; camera_name: string; hours: number[] }>;
  people_by_hour: number[];
  vehicles_by_hour: number[];
  busiest_hour: number | null;
  busiest_camera: string | null;
}

// --- People (own-camera sightings + history) -------------------------------- //

export interface PersonRow {
  sighting_id: string | null;        // null for detection-only rows (no face)
  source?: 'face' | 'detection';
  camera_id: string;
  camera_name: string;
  ts: string;
  bbox?: number[] | null;
  image_url?: string | null;
  matched_person_id?: string | null;
  matched_label?: string | null;
  matched_details?: string | null;   // operator's stored notes about this enrolled person
  match_score?: number | null;
}

export interface PriorSighting {
  camera_id: string;
  ts: string;
  score: number;
  matched_person_id?: string | null;
  sighting_id?: string | null;
  frame_url?: string | null;
  bbox?: number[] | null;
}

export interface PersonHistoryResult {
  seen_before: boolean;
  times_seen: number;
  distinct_cameras: string[];
  first_seen?: string | null;
  last_seen?: string | null;
  watchlist_person_id?: string | null;
  prior_sightings: PriorSighting[];
  summary: string;
}

// --- Intel data sources ----------------------------------------------------- //

export interface UserSource {
  source_id: string;
  name: string;
  domain: string;
  lawful_basis: string;
  retention_days: number;
  description: string;
  endpoint: string;
  notes: string;
  enabled: boolean;
  created_at: string;
  updated_at: string;
  record_count: number;
}

export interface CatalogueEntry {
  key: string;
  name: string;
  provides: string;
  why: string;
  status: 'available' | 'gated' | 'blocked' | 'rejected';
  requirement: string;
  url?: string;
  domain: string;
  lawful_basis: string;
  recommended?: boolean;
}

export interface SourceVocab {
  sources: UserSource[];
  catalogue: CatalogueEntry[];
  domains: Array<{ value: string; label: string }>;
  lawful_bases: Array<{ value: string; label: string }>;
  boundary: string;
}

export interface HotlistEntry {
  plate: string;
  reason: string;
  added_ts: string;
  source_ref: string;
  metadata?: Record<string, any>;
}

// --- Security Advisor + brief ----------------------------------------------- //

export interface BriefFinding {
  kind: string;
  detail: string;
  severity_hint: string;
  incident_ids: string[];
}

export interface SiteBrief {
  site_id: string;
  site_name: string;
  subject_type: string;
  window_hours: number;
  incident_count: number;
  coverage: {
    cameras_configured: string[];
    cameras_with_activity: string[];
    quiet_cameras: string[];
    scoped_to_site_cameras: boolean;
  };
  findings: BriefFinding[];
  narrative: string;
  source: string;
  brief_sections: string[];
  area_context?: any;
  disclaimer: string;
  generated_ts: string;
}

export interface Recommendation {
  key: string;
  title: string;
  detail: string;
  priority: 'critical' | 'high' | 'medium' | 'low';
  evidence: string;
  action: string;
  link: string;
}

export interface AdvisorResult {
  summary: string;
  recommendations: Recommendation[];
  generated_ts: string;
  observed: Record<string, any>;
  note: string;
}

/** Owner-tunable AI spend controls (Costs page). */
export interface AiConfig {
  vision_model: string;
  paid_min_gap_seconds: number;
  narrate_vehicles: boolean;
  narrate_people: boolean;
  schedule: 'always' | 'after_hours' | 'night';
  daily_budget_usd: number;
}

export interface AiConfigResponse {
  config: AiConfig;
  vision_models: Record<string, { label: string; in_usd: number; out_usd: number }>;
}

/** An explicit pattern sentence ("Vehicle C is NEW to the scene — first seen 14:02"). */
export interface PatternFinding {
  kind: 'new' | 'regular' | 'resident' | 'occasional' | 'scene' | 'people';
  entity_id: string | null;
  label: string;
  owner_label: string | null;
  text: string;
}

/** A cited, actionable way to improve the security setup. */
export interface SecuritySuggestion {
  title: string;
  why: string;
  link: string;
  action: string;
}


/** Vehicle history — how often a recurring vehicle (ReID cluster) has been seen
 *  over a window. Continuity from our own cameras, never identity. */
export interface VehicleHistory {
  entity_id: string;
  window: string;
  owner_label: string | null;
  owner_details?: string | null;      // what the owner knows about this vehicle
  familiarity: 'resident' | 'regular' | 'new' | 'occasional';
  count: number;
  days: number;
  first_seen: string;
  last_seen: string;
  cameras: string[];
  hours: number[];
  colour?: string | null;
  body?: string | null;
  plate?: string | null;              // most-read plate — the stable identity
  plate_region?: string | null;
  frame_url?: string | null;                                   // representative photo
  bbox?: number[] | null;
  frames?: Array<{
    ts: string; camera_id: string; frame_url: string; bbox: number[];
    frame_id?: string;
    description?: string | null;   // what the AI read in THIS snapshot
    note?: string | null;          // the owner's own words about it
  }>;
  frames_total?: number;
  frames_offset?: number;
  per_day: Array<{ day: string; count: number }>;
  trail: Array<{ camera_id: string; ts: string }>;
}
