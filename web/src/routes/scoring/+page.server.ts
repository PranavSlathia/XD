import { fetchJson } from '$lib/api';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ fetch }) => {
  try {
    const weights = await fetchJson<Record<string, unknown>>('/api/scoring-weights', undefined, fetch);
    return { weights, error: null as string | null };
  } catch (e) {
    return { weights: null, error: (e as Error).message };
  }
};
