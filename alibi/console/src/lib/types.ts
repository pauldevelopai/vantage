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

/** Service usage & estimated cost. */
export interface CostSummary {
  currency: string;
  window_days: number;
  total_usd: number;
  by_service: Record<string, { calls: number; input_tokens: number; output_tokens: number; usd: number }>;
  by_day: Array<{ day: string; usd: number; calls: number }>;
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

export interface DashboardOverview {
  range: string;
  generated_at: string;
  kpis: { events: number; alerts: number; people: number; vehicles: number };
  by_type: Array<{ type: string; count: number }>;
  over_time: Array<{ hour: string; events: number; alerts: number }>;
  recent: DashboardRow[];
  cameras: DashboardCamera[];
  alerts: DashboardRow[];
}

// --- People (own-camera sightings + history) -------------------------------- //

export interface PersonRow {
  sighting_id: string;
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
