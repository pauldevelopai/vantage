// Server-Sent Events manager for live incident updates in the Control Room.
//
// The backend streams incident upserts + heartbeats from GET /stream/incidents
// (via the /api proxy). EventSource can't set custom headers, so the JWT is
// passed as a ?token= query param, which the backend accepts for this route.

import type { SSEEvent } from './types';
import { getToken } from './auth';

type EventCallback = (event: SSEEvent) => void;

class SSEManager {
  private source: EventSource | null = null;
  private listeners = new Set<EventCallback>();

  /** Open the stream (no-op if already connected). Auto-reconnects. */
  connect(): void {
    if (this.source) return;
    const token = getToken();
    const url = `/api/stream/incidents${token ? `?token=${encodeURIComponent(token)}` : ''}`;
    const es = new EventSource(url);
    es.onmessage = (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data) as SSEEvent;
        this.listeners.forEach((cb) => cb(data));
      } catch {
        // ignore malformed frames (e.g. comments / keep-alives)
      }
    };
    es.onerror = () => {
      // EventSource reconnects on its own; nothing to do here.
    };
    this.source = es;
  }

  /** Subscribe to events; returns an unsubscribe function. */
  onEvent(callback: EventCallback): () => void {
    this.listeners.add(callback);
    return () => {
      this.listeners.delete(callback);
    };
  }

  /** Close the stream and drop all listeners. */
  disconnect(): void {
    if (this.source) {
      this.source.close();
      this.source = null;
    }
    this.listeners.clear();
  }
}

export const sseManager = new SSEManager();
