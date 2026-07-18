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
  times_seen: number;                // 0 for detection-only rows (no embedding to link)
  first_seen: string | null;
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
  watching_for: WatchingFor | null;
  patterns: DashboardPatterns | null;
  situations: DashboardSituation[];
  recurring_vehicles: RecurringVehicle[];
  pattern_findings: PatternFinding[];
  security_suggestions: SecuritySuggestion[];
}

/** An appearance-ReID cluster: the SAME vehicle seen repeatedly, linked by our
 *  own cameras' embeddings. Anonymous ("Vehicle A") — continuity, no identity. */
export interface RecurringVehicle {
  label: string;
  entity_id: string;
  owner_label: string | null;        // the owner's own name for it ("Paul's Fortuner")
  familiarity: 'resident' | 'regular' | 'new' | 'occasional';
  count: number;
  days: number;
  first_seen: string;
  last_seen: string;
  cameras: string[];
  busiest_hour_utc: number | null;
}

/** One incident on the Overview's Situations panel. The machine's ceiling is
 *  tier "review" — "confirmed" (and any crime word in its label) only ever
 *  comes from a person, whose name is attached. */
export interface DashboardSituation {
  incident_id: string;
  tier: 'confirmed' | 'review' | 'noted';
  status?: string;
  severity: number;
  ts: string;
  camera_id: string | null;
  camera_name: string | null;
  title: string | null;
  event_type: string | null;
  description: string;
  snapshot_url: string | null;
  confirmed: { by: string; ts: string; label: string | null; notes?: string } | null;
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
