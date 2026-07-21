// API client for Alibi backend

import type { DashboardOverview, PersonRow, PersonHistoryResult, SourceVocab, UserSource, HotlistEntry, SiteBrief, AdvisorResult, IncidentSummary, IncidentDetail, IncidentExplanation, DecisionRequest, Settings, ShiftReport, Camera, TrailEntry, Site, Posture, SubjectType, CostSummary, VehicleHistory } from './types';
import { getToken } from './auth';

const API_BASE = '/api';

// Helper to get auth headers
function getHeaders(): HeadersInit {
  const token = getToken();
  const headers: HeadersInit = {
    'Content-Type': 'application/json',
  };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  return headers;
}

// Helper to handle fetch with auth and 401 redirect
async function fetchWithAuth(url: string, options: RequestInit = {}): Promise<Response> {
  const headers = getHeaders();
  const response = await fetch(url, {
    ...options,
    headers: {
      ...headers,
      ...options.headers,
    },
  });

  // If unauthorized, redirect to login
  if (response.status === 401) {
    localStorage.removeItem('alibi_token');
    localStorage.removeItem('alibi_user');
    window.location.href = '/login';
    throw new Error('Unauthorized');
  }

  return response;
}

export const api = {
  // Incidents
  async listIncidents(params?: { status?: string; since?: string; limit?: number }): Promise<IncidentSummary[]> {
    const query = new URLSearchParams();
    if (params?.status) query.set('status', params.status);
    if (params?.since) query.set('since', params.since);
    if (params?.limit) query.set('limit', params.limit.toString());
    
    const res = await fetchWithAuth(`${API_BASE}/incidents?${query}`);
    if (!res.ok) throw new Error(`Failed to fetch incidents: ${res.statusText}`);
    return res.json();
  },

  async getIncident(incidentId: string): Promise<IncidentDetail> {
    const res = await fetchWithAuth(`${API_BASE}/incidents/${incidentId}`);
    if (!res.ok) throw new Error(`Failed to fetch incident: ${res.statusText}`);
    return res.json();
  },

  async getIncidentExplanation(incidentId: string): Promise<IncidentExplanation> {
    const res = await fetchWithAuth(`${API_BASE}/incidents/${incidentId}/explanation`);
    if (!res.ok) throw new Error(`Failed to fetch explanation: ${res.statusText}`);
    return res.json();
  },

  async recordDecision(incidentId: string, decision: DecisionRequest): Promise<any> {
    const res = await fetchWithAuth(`${API_BASE}/incidents/${incidentId}/decision`, {
      method: 'POST',
      body: JSON.stringify(decision),
    });
    if (!res.ok) throw new Error(`Failed to record decision: ${res.statusText}`);
    return res.json();
  },

  // Reports
  async generateShiftReport(start_ts: string, end_ts: string): Promise<ShiftReport> {
    const res = await fetchWithAuth(`${API_BASE}/reports/shift`, {
      method: 'POST',
      body: JSON.stringify({ start_ts, end_ts }),
    });
    if (!res.ok) throw new Error(`Failed to generate report: ${res.statusText}`);
    return res.json();
  },

  // Settings
  async getSettings(): Promise<Settings> {
    const res = await fetchWithAuth(`${API_BASE}/settings`);
    if (!res.ok) throw new Error(`Failed to fetch settings: ${res.statusText}`);
    return res.json();
  },

  async updateSettings(settings: Partial<Settings>): Promise<any> {
    const res = await fetchWithAuth(`${API_BASE}/settings`, {
      method: 'PUT',
      body: JSON.stringify(settings),
    });
    if (!res.ok) throw new Error(`Failed to update settings: ${res.statusText}`);
    return res.json();
  },

  // Patterns (Phase 2)
  async getActivity(window: string = '24h'): Promise<any> {
    const res = await fetchWithAuth(`${API_BASE}/patterns/activity?window=${encodeURIComponent(window)}`);
    if (!res.ok) throw new Error(`Failed to fetch activity: ${res.statusText}`);
    return res.json();
  },

  async getPlateIncidents(plate: string, windowMinutes: number = 30): Promise<any> {
    const res = await fetchWithAuth(`${API_BASE}/patterns/plate/${encodeURIComponent(plate)}/incidents?window_minutes=${windowMinutes}`);
    if (!res.ok) throw new Error(`Failed to fetch plate incidents: ${res.statusText}`);
    return res.json();
  },

  async getVehicleReview(): Promise<any> {
    const res = await fetchWithAuth(`${API_BASE}/vehicles/review`);
    if (!res.ok) throw new Error('Failed to load review queue');
    return res.json();
  },

  async decideVehicleReview(itemId: string, body: { decision: 'confirm' | 'reject'; make?: string; model?: string; colour?: string; body?: string }): Promise<any> {
    const res = await fetchWithAuth(`${API_BASE}/vehicles/review/${encodeURIComponent(itemId)}`, {
      method: 'POST', body: JSON.stringify(body),
    });
    if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || 'Failed'); }
    return res.json();
  },

  async submitFieldReport(body: { subject: string; note: string; camera_id?: string; location?: string; tags?: Record<string, string> }): Promise<any> {
    const res = await fetchWithAuth(`${API_BASE}/reports/field`, {
      method: 'POST', body: JSON.stringify(body),
    });
    if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || 'Failed to log report'); }
    return res.json();
  },

  async getVehicleHistory(entityId: string, window: string = '7d'): Promise<VehicleHistory> {
    const res = await fetchWithAuth(`${API_BASE}/patterns/vehicle/${encodeURIComponent(entityId)}?window=${window}`);
    if (!res.ok) throw new Error('Failed to fetch vehicle history');
    return res.json();
  },

  async getPersonHistory(sightingId: string): Promise<PersonHistoryResult> {
    const res = await fetchWithAuth(`${API_BASE}/patterns/person-history/${encodeURIComponent(sightingId)}`);
    if (!res.ok) throw new Error(`Failed to fetch person history: ${res.statusText}`);
    return res.json();
  },

  // Simulator endpoints
  async startSimulator(config: {
    scenario: string;
    rate_per_min: number;
    seed?: number;
  }): Promise<{ status: string; scenario: string; rate_per_min: number; seed?: number }> {
    const response = await fetchWithAuth(`${API_BASE}/sim/start`, {
      method: 'POST',
      body: JSON.stringify(config),
    });
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || 'Failed to start simulator');
    }
    return response.json();
  },

  async stopSimulator(): Promise<{ status: string }> {
    const response = await fetchWithAuth(`${API_BASE}/sim/stop`, {
      method: 'POST',
    });
    if (!response.ok) throw new Error('Failed to stop simulator');
    return response.json();
  },

  async getSimulatorStatus(): Promise<{
    running: boolean;
    events_generated: number;
    incidents_created: number;
    rate_actual?: number;
    rate_target?: number;
    scenario?: string;
    seed?: number;
    elapsed_seconds?: number;
  }> {
    const response = await fetchWithAuth(`${API_BASE}/sim/status`);
    if (!response.ok) throw new Error('Failed to get simulator status');
    return response.json();
  },

  async replayEvents(data: {
    jsonl_data?: string;
    file_path?: string;
  }): Promise<{
    status: string;
    events_replayed: number;
    incidents_created: number;
    errors: string[];
  }> {
    const response = await fetchWithAuth(`${API_BASE}/sim/replay`, {
      method: 'POST',
      body: JSON.stringify(data),
    });
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || 'Failed to replay events');
    }
    return response.json();
  },

  // Approval (supervisor only)
  async approveIncident(incidentId: string, notes?: string): Promise<any> {
    const res = await fetchWithAuth(`${API_BASE}/incidents/${incidentId}/approve`, {
      method: 'POST',
      body: JSON.stringify({ notes }),
    });
    if (!res.ok) throw new Error(`Failed to approve incident: ${res.statusText}`);
    return res.json();
  },

  // Evidence export
  async exportEvidence(incidentId: string): Promise<{ export_path: string }> {
    const res = await fetchWithAuth(`${API_BASE}/incidents/${incidentId}/export`, {
      method: 'POST',
    });
    if (!res.ok) throw new Error(`Failed to export evidence: ${res.statusText}`);
    return res.json();
  },

  // Metrics
  async getMetricsSummary(range?: string): Promise<any> {
    const query = range ? `?range=${range}` : '';
    const res = await fetchWithAuth(`${API_BASE}/metrics/summary${query}`);
    if (!res.ok) throw new Error(`Failed to fetch metrics: ${res.statusText}`);
    return res.json();
  },

  // Vehicle Search
  async searchVehicles(params: {
    plate?: string;
    make?: string;
    model?: string;
    color?: string;
    camera_id?: string;
    from_ts?: string;
    to_ts?: string;
    limit?: number;
  }): Promise<any> {
    const queryParams = new URLSearchParams();
    if (params.plate) queryParams.append('plate', params.plate);
    if (params.make) queryParams.append('make', params.make);
    if (params.model) queryParams.append('model', params.model);
    if (params.color) queryParams.append('color', params.color);
    if (params.camera_id) queryParams.append('camera_id', params.camera_id);
    if (params.from_ts) queryParams.append('from_ts', params.from_ts);
    if (params.to_ts) queryParams.append('to_ts', params.to_ts);
    if (params.limit) queryParams.append('limit', params.limit.toString());

    const res = await fetchWithAuth(`${API_BASE}/search/vehicles?${queryParams}`);
    if (!res.ok) throw new Error('Search failed');
    return res.json();
  },

  // Cameras
  async listCameras(): Promise<{ cameras: Camera[] }> {
    const res = await fetchWithAuth(`${API_BASE}/cameras`);
    if (!res.ok) throw new Error('Failed to fetch cameras');
    return res.json();
  },

  async addCamera(camera: {
    camera_id: string;
    name: string;
    source?: string;
    source_type?: string;
    location?: string;
    area?: string;
    site_id?: string;
    vms_config?: Record<string, any>;
  }): Promise<Camera> {
    const res = await fetchWithAuth(`${API_BASE}/cameras`, {
      method: 'POST',
      body: JSON.stringify(camera),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Failed to add camera');
    }
    return res.json();
  },

  async updateCamera(cameraId: string, updates: Partial<Camera>): Promise<Camera> {
    const res = await fetchWithAuth(`${API_BASE}/cameras/${cameraId}`, {
      method: 'PUT',
      body: JSON.stringify(updates),
    });
    if (!res.ok) throw new Error('Failed to update camera');
    return res.json();
  },

  // Live view — tell the cloud a camera is being watched (heartbeat while open).
  async watchCamera(cameraId: string): Promise<{ expires_at: number }> {
    const res = await fetchWithAuth(`${API_BASE}/cameras/${cameraId}/watch`, { method: 'POST' });
    if (!res.ok) throw new Error('Failed to start live view');
    return res.json();
  },

  async deleteCamera(cameraId: string): Promise<any> {
    const res = await fetchWithAuth(`${API_BASE}/cameras/${cameraId}`, {
      method: 'DELETE',
    });
    if (!res.ok) throw new Error('Failed to delete camera');
    return res.json();
  },

  async testCamera(cameraId: string): Promise<{ ok: boolean; resolution?: string; fps?: number; error?: string }> {
    const res = await fetchWithAuth(`${API_BASE}/cameras/${cameraId}/test`, {
      method: 'POST',
    });
    if (!res.ok) throw new Error('Failed to test camera');
    return res.json();
  },

  // Camera Network Scan
  async scanCameras(): Promise<{ scan_id: string; status: string }> {
    const res = await fetchWithAuth(`${API_BASE}/cameras/scan`, { method: 'POST' });
    if (!res.ok) throw new Error('Failed to start camera scan');
    return res.json();
  },

  async getScanStatus(): Promise<{
    status: string;
    discovered: Array<{
      ip: string;
      port: number;
      source_type: string;
      rtsp_url: string;
      name: string;
      manufacturer: string;
      model: string;
      resolution: string;
      discovery_method: string;
      already_registered: boolean;
    }>;
    total: number;
    new_cameras: number;
  }> {
    const res = await fetchWithAuth(`${API_BASE}/cameras/scan/status`);
    if (!res.ok) throw new Error('Failed to get scan status');
    return res.json();
  },

  // Sites — what Vantage is protecting (home / office / neighbourhood)
  async listSites(): Promise<{ sites: Site[] }> {
    const res = await fetchWithAuth(`${API_BASE}/sites`);
    if (!res.ok) throw new Error('Failed to fetch sites');
    return res.json();
  },

  async getSitePostures(): Promise<{ postures: Record<SubjectType, Posture> }> {
    const res = await fetchWithAuth(`${API_BASE}/sites/postures`);
    if (!res.ok) throw new Error('Failed to fetch postures');
    return res.json();
  },

  async createSite(site: {
    name: string;
    subject_type: SubjectType;
    area?: string;
    address?: string;
    timezone?: string;
    normal_hours?: Record<string, any>;
    camera_ids?: string[];
    notes?: string;
    context?: string;
  }): Promise<Site> {
    const res = await fetchWithAuth(`${API_BASE}/sites`, {
      method: 'POST',
      body: JSON.stringify(site),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Failed to create site');
    }
    return res.json();
  },

  async updateSite(siteId: string, updates: Partial<{
    name: string;
    subject_type: SubjectType;
    area: string;
    address: string;
    timezone: string;
    normal_hours: Record<string, any>;
    camera_ids: string[];
    notes: string;
    context: string;
  }>): Promise<Site> {
    const res = await fetchWithAuth(`${API_BASE}/sites/${siteId}`, {
      method: 'PUT',
      body: JSON.stringify(updates),
    });
    if (!res.ok) throw new Error('Failed to update site');
    return res.json();
  },

  async deleteSite(siteId: string): Promise<any> {
    const res = await fetchWithAuth(`${API_BASE}/sites/${siteId}`, {
      method: 'DELETE',
    });
    if (!res.ok) throw new Error('Failed to delete site');
    return res.json();
  },

  // Camera Bridge — scan a user's own WiFi via a local agent
  async listBridges(): Promise<{ bridges: Array<{
    bridge_id: string; name: string; created_at: string;
    last_seen: string | null; site_hint: string; online: boolean;
  }> }> {
    const res = await fetchWithAuth(`${API_BASE}/cameras/bridge`);
    if (!res.ok) throw new Error('Failed to list bridges');
    return res.json();
  },

  async downloadBridgeAgent(): Promise<void> {
    const res = await fetchWithAuth(`${API_BASE}/cameras/bridge/download`);
    if (!res.ok) throw new Error('Failed to download the bridge agent');
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'vantage_bridge.py';
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  },

  // The recording agent — a self-contained zipapp for the always-on PC.
  async downloadRecorder(): Promise<void> {
    const res = await fetchWithAuth(`${API_BASE}/cameras/bridge/download-recorder`);
    if (!res.ok) throw new Error('Failed to download the recorder');
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'vantage_recorder.pyz';
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  },

  // A double-clickable launcher for this computer (recorder embedded).
  async downloadRecorderLauncher(platform: 'mac' | 'windows'): Promise<void> {
    const res = await fetchWithAuth(`${API_BASE}/cameras/bridge/download-launcher?platform=${platform}`);
    if (!res.ok) throw new Error('Failed to prepare the launcher');
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = platform === 'windows' ? 'Vantage Recorder.bat' : 'Vantage Recorder.command';
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  },

  async renameBridge(bridgeId: string, name: string): Promise<void> {
    const res = await fetchWithAuth(`${API_BASE}/cameras/bridge/${bridgeId}`, {
      method: 'PATCH',
      body: JSON.stringify({ name }),
    });
    if (!res.ok) throw new Error('Failed to rename PC');
  },

  async removeBridge(bridgeId: string): Promise<void> {
    const res = await fetchWithAuth(`${API_BASE}/cameras/bridge/${bridgeId}`, { method: 'DELETE' });
    if (!res.ok) throw new Error('Failed to remove PC');
  },

  async scanViaBridge(bridgeId: string, cidr?: string): Promise<{ job_id: string; status: string }> {
    const res = await fetchWithAuth(`${API_BASE}/cameras/bridge/${bridgeId}/scan`, {
      method: 'POST',
      body: JSON.stringify(cidr ? { cidr } : {}),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Failed to start scan');
    }
    return res.json();
  },

  async getBridgeScanStatus(jobId: string): Promise<{
    job_id: string; status: string; error: string;
    results: Array<Record<string, any>>;
  }> {
    const res = await fetchWithAuth(`${API_BASE}/cameras/bridge/scan/${jobId}`);
    if (!res.ok) throw new Error('Failed to get scan status');
    return res.json();
  },

  async getLatestBridgeScan(bridgeId: string): Promise<{
    job: { job_id: string; status: string; results: Array<Record<string, any>> } | null;
  }> {
    const res = await fetchWithAuth(`${API_BASE}/cameras/bridge/${bridgeId}/latest-scan`);
    if (!res.ok) throw new Error('Failed to get latest scan');
    return res.json();
  },

  async addDiscoveredCamera(camera: {
    ip: string;
    port: number;
    rtsp_url: string;
    source_type: string;
    name?: string;
    location?: string;
    username?: string;
    password?: string;
    vendor?: string;
    manufacturer?: string;
    site_id?: string;
  }): Promise<any> {
    const res = await fetchWithAuth(`${API_BASE}/cameras/add-discovered`, {
      method: 'POST',
      body: JSON.stringify(camera),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Failed to add camera');
    }
    return res.json();
  },

  // Semantic Search
  async semanticSearch(params: {
    query: string;
    limit?: number;
    min_score?: number;
    source?: string;
    camera_id?: string;
    hours?: number;
    threat_level?: string;
  }): Promise<{
    query: string;
    results: Array<{
      source: string;
      score: number;
      timestamp: string;
      camera_id: string;
      description: string;
      snapshot_url: string | null;
      thumbnail_url: string | null;
      detected_objects: string[];
      threat_level: string;
      metadata: Record<string, any>;
    }>;
    total: number;
  }> {
    const res = await fetchWithAuth(`${API_BASE}/search/semantic`, {
      method: 'POST',
      body: JSON.stringify(params),
    });
    if (!res.ok) throw new Error('Search failed');
    return res.json();
  },

  async getSearchStats(): Promise<Record<string, any>> {
    const res = await fetchWithAuth(`${API_BASE}/search/stats`);
    if (!res.ok) throw new Error('Failed to get search stats');
    return res.json();
  },

  // Entity Trail (cross-camera tracking)
  async getEntityTrail(entityType: string, entityId: string, hours?: number): Promise<{ entity_type: string; entity_id: string; trail: TrailEntry[] }> {
    const query = hours ? `?hours=${hours}` : '';
    const res = await fetchWithAuth(`${API_BASE}/trail/${entityType}/${encodeURIComponent(entityId)}${query}`);
    if (!res.ok) throw new Error('Failed to fetch trail');
    return res.json();
  },

  // Watchlist
  async getWatchlist(): Promise<{ entries: any[]; total: number }> {
    const res = await fetchWithAuth(`${API_BASE}/watchlist`);
    if (!res.ok) throw new Error('Failed to fetch watchlist');
    return res.json();
  },

  async enrollWatchlistFace(formData: FormData): Promise<any> {
    const token = getToken();
    const res = await fetch(`${API_BASE}/watchlist/enroll`, {
      method: 'POST',
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      body: formData,
    });
    if (res.status === 401) {
      localStorage.removeItem('alibi_token');
      localStorage.removeItem('alibi_user');
      window.location.href = '/login';
      throw new Error('Unauthorized');
    }
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Enrollment failed');
    }
    return res.json();
  },

  /** Enrol from a face the cameras already saw — a name, optional details, and a
   *  button. Builds the recognition DB: future sightings say the name (+ notes). */
  async enrollFaceFromSighting(sightingId: string, label: string, details?: string): Promise<any> {
    const res = await fetchWithAuth(`${API_BASE}/watchlist/enroll-sighting`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sighting_id: sightingId, label, details: details || '' }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Enrolment failed');
    }
    return res.json();
  },

  async removeWatchlistEntry(personId: string): Promise<any> {
    const res = await fetchWithAuth(`${API_BASE}/watchlist/${encodeURIComponent(personId)}`, {
      method: 'DELETE',
    });
    if (!res.ok) throw new Error('Failed to remove entry');
    return res.json();
  },

  async searchWatchlistByFace(formData: FormData): Promise<any> {
    const token = getToken();
    const res = await fetch(`${API_BASE}/watchlist/search`, {
      method: 'POST',
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      body: formData,
    });
    if (res.status === 401) {
      localStorage.removeItem('alibi_token');
      localStorage.removeItem('alibi_user');
      window.location.href = '/login';
      throw new Error('Unauthorized');
    }
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Search failed');
    }
    return res.json();
  },

  // External intelligence — the non-personal reference data the engine harvests.
  async getIntelligenceData(): Promise<{
    boundary: string;
    sources: Array<{ source_id: string; domain: string; description: string; apify_actor: string | null; retention_days: number }>;
    stats: { total_live_records: number; by_source: Record<string, number>; by_domain: Record<string, number> };
    records: Array<{ source_id: string; domain: string; lawful_basis: string; ingested_at: string; retention_until: string; payload: Record<string, any> }>;
  }> {
    const res = await fetchWithAuth(`${API_BASE}/intelligence/data`);
    if (!res.ok) throw new Error('Failed to load intelligence data');
    return res.json();
  },

  // Service usage & estimated cost.
  async getCostSummary(): Promise<CostSummary> {
    const res = await fetchWithAuth(`${API_BASE}/costs/summary`);
    if (!res.ok) throw new Error('Failed to load costs');
    return res.json();
  },

  /** Vision stack + data-engine feed status for the Intel page. */
  async getMlStatus(): Promise<any> {
    const res = await fetchWithAuth(`${API_BASE}/intelligence/ml-status`);
    if (!res.ok) throw new Error('Failed to load ML status');
    return res.json();
  },

  /** Name a recurring vehicle ("Paul's Fortuner"); empty label removes it. */
  async setVehicleLabel(entityId: string, label: string, plate?: string | null,
                        details?: string | null): Promise<any> {
    const res = await fetchWithAuth(`${API_BASE}/vehicles/entity-label`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ entity_id: entityId, label, plate: plate || null,
                             details: details || null }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Failed to save label');
    }
    return res.json();
  },

  /** AI spend controls: vision model, paid-call cap, vehicle narration. */
  async getAiConfig(): Promise<import('./types').AiConfigResponse> {
    const res = await fetchWithAuth(`${API_BASE}/costs/ai-config`);
    if (!res.ok) throw new Error('Failed to load AI config');
    return res.json();
  },

  async setAiConfig(update: Partial<import('./types').AiConfig>): Promise<import('./types').AiConfigResponse> {
    const res = await fetchWithAuth(`${API_BASE}/costs/ai-config`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(update),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Failed to update AI config');
    }
    return res.json();
  },

  /** Record the account's API credit balance (from console.anthropic.com). */
  async setApiCredits(balanceUsd: number): Promise<any> {
    const res = await fetchWithAuth(`${API_BASE}/costs/credits`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ balance_usd: balanceUsd }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Failed to update credits');
    }
    return res.json();
  },

  async getRecentPeople(hours: number = 168): Promise<{ people: PersonRow[]; count: number; window_hours: number }> {
    const res = await fetchWithAuth(`${API_BASE}/people/recent?hours=${hours}`);
    if (!res.ok) throw new Error('Failed to load people');
    return res.json();
  },

  /** Every DISTINCT vehicle (appearance clusters) — what the Overview KPI counts. */
  async getDistinctVehicles(window: string = '7d'): Promise<{ window: string; count: number; vehicles: any[] }> {
    const res = await fetchWithAuth(`${API_BASE}/vehicles/distinct?window=${window}`);
    if (!res.ok) throw new Error('Failed to load distinct vehicles');
    return res.json();
  },

  /** Recorder behaviour the agent honours live (e.g. local Ollama vision on/off). */
  async getRecorderSettings(): Promise<{ local_vision: boolean }> {
    const res = await fetchWithAuth(`${API_BASE}/recorders/settings`);
    if (!res.ok) throw new Error('Failed to load recorder settings');
    return res.json();
  },
  async setRecorderSettings(patch: { local_vision?: boolean }): Promise<{ local_vision: boolean }> {
    const res = await fetchWithAuth(`${API_BASE}/recorders/settings`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(patch),
    });
    if (!res.ok) throw new Error('Failed to save recorder settings');
    return res.json();
  },

  async getSiteBrief(siteId: string, windowHours: number = 24): Promise<SiteBrief> {
    const res = await fetchWithAuth(`${API_BASE}/sites/${encodeURIComponent(siteId)}/brief?window_hours=${windowHours}`);
    if (!res.ok) throw new Error('Failed to load the brief');
    return res.json();
  },

  async getAdvisor(siteId?: string): Promise<AdvisorResult> {
    const q = siteId ? `?site_id=${encodeURIComponent(siteId)}` : '';
    const res = await fetchWithAuth(`${API_BASE}/advisor${q}`);
    if (!res.ok) throw new Error('Failed to load recommendations');
    return res.json();
  },

  async getHotlistPlates(): Promise<{ entries: HotlistEntry[]; total: number }> {
    const res = await fetchWithAuth(`${API_BASE}/hotlist/plates`);
    if (!res.ok) throw new Error('Failed to load the hotlist');
    return res.json();
  },

  async addHotlistPlate(body: { plate: string; reason: string; source_ref: string }): Promise<any> {
    const res = await fetchWithAuth(`${API_BASE}/hotlist/plates`, {
      method: 'POST', body: JSON.stringify(body),
    });
    if (!res.ok) {
      const e = await res.json().catch(() => ({}));
      throw new Error(e.detail || 'Failed to add the plate');
    }
    return res.json();
  },

  async removeHotlistPlate(plate: string): Promise<void> {
    const res = await fetchWithAuth(`${API_BASE}/hotlist/plates/${encodeURIComponent(plate)}`, { method: 'DELETE' });
    if (!res.ok) throw new Error('Failed to remove the plate');
  },

  async getIntelSources(): Promise<SourceVocab> {
    const res = await fetchWithAuth(`${API_BASE}/intelligence/sources`);
    if (!res.ok) throw new Error('Failed to load intel sources');
    return res.json();
  },

  async createIntelSource(body: Record<string, any>): Promise<UserSource> {
    const res = await fetchWithAuth(`${API_BASE}/intelligence/sources`, {
      method: 'POST', body: JSON.stringify(body),
    });
    if (!res.ok) {
      const e = await res.json().catch(() => ({}));
      throw new Error(e.detail || 'Failed to add the source');
    }
    return res.json();
  },

  async feedIntelSource(sourceId: string, records: any[]): Promise<{ written: number; rejected: string[] }> {
    const res = await fetchWithAuth(`${API_BASE}/intelligence/sources/${encodeURIComponent(sourceId)}/records`, {
      method: 'POST', body: JSON.stringify({ records }),
    });
    if (!res.ok) {
      const e = await res.json().catch(() => ({}));
      throw new Error(e.detail || 'Failed to store records');
    }
    return res.json();
  },

  async deleteIntelSource(sourceId: string): Promise<void> {
    const res = await fetchWithAuth(`${API_BASE}/intelligence/sources/${encodeURIComponent(sourceId)}`, { method: 'DELETE' });
    if (!res.ok) throw new Error('Failed to remove the source');
  },

  async getDashboardOverview(range: string = '24h'): Promise<DashboardOverview> {
    const res = await fetchWithAuth(`${API_BASE}/dashboard/overview?range=${encodeURIComponent(range)}`);
    if (!res.ok) throw new Error('Failed to load the dashboard');
    return res.json();
  },
};
