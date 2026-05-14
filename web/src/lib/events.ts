/** SSE consumer store. Emits the latest event message. */
import { writable, type Writable } from 'svelte/store';
import { API_BASE } from './api';

export interface DhEvent {
  raw: string;
  parsed?: Record<string, unknown>;
  at: number;
}

export const events: Writable<DhEvent | null> = writable(null);

let started = false;
let source: EventSource | null = null;

export function startEventStream(): void {
  if (started || typeof window === 'undefined') return;
  started = true;
  source = new EventSource(`${API_BASE}/api/events`);
  source.onmessage = (ev: MessageEvent<string>) => {
    let parsed: Record<string, unknown> | undefined;
    try {
      parsed = JSON.parse(ev.data) as Record<string, unknown>;
    } catch {
      parsed = undefined;
    }
    events.set({ raw: ev.data, parsed, at: Date.now() });
  };
}

export function stopEventStream(): void {
  source?.close();
  source = null;
  started = false;
}
