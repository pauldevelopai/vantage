// API client for Alibi backend

import type { IncidentSummary, IncidentDetail, DecisionRequest, Settings, ShiftReport, Camera, TrailEntry } from './types';
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

  async addDiscoveredCamera(camera: {
    ip: string;
    port: number;
    rtsp_url: string;
    source_type: string;
    name?: string;
    location?: string;
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
};
