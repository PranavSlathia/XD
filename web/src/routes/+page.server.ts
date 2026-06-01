import { fetchJson, type DigestItem } from '$lib/api';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ fetch }) => {
  try {
    const items = await fetchJson<DigestItem[]>('/api/digest/today', undefined, fetch);
    return { items, error: null as string | null };
  } catch (e) {
    return { items: [] as DigestItem[], error: (e as Error).message };
  }
};
