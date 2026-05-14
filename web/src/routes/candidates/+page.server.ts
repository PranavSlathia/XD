import { fetchJson, type CandidateListItem } from '$lib/api';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ url }) => {
  const params = new URLSearchParams();
  const minScore = url.searchParams.get('min_score');
  const status = url.searchParams.get('status');
  if (minScore) params.set('min_score', minScore);
  if (status) params.set('status', status);
  params.set('limit', '200');
  try {
    const items = await fetchJson<CandidateListItem[]>(`/api/candidates?${params.toString()}`);
    return { items, error: null as string | null };
  } catch (e) {
    return { items: [] as CandidateListItem[], error: (e as Error).message };
  }
};
