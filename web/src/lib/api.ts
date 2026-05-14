import { env } from '$env/dynamic/public';

export const API_BASE: string =
  env.PUBLIC_DH_API_BASE_URL ?? 'http://dh-api:8000';

export interface CandidateListItem {
  id: number;
  domain: string;
  composite_score: number | null;
  current_status: string | null;
  availability_confidence: string | null;
  score_version: number | null;
  hard_filtered: boolean;
  hard_filter_reason: string | null;
  first_observed: string;
  last_observed: string;
}

export interface DigestItem {
  domain: string;
  composite_score: number | null;
  current_status: string | null;
  quote_price_micros: number | null;
  top_reasons: string[];
}

export async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, init);
  if (!res.ok) throw new Error(`API ${path} failed: ${res.status}`);
  return (await res.json()) as T;
}
