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
