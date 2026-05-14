import { fetchJson } from '$lib/api';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ params }) => {
  try {
    const detail = await fetchJson<Record<string, unknown>>(
      `/api/candidates/${encodeURIComponent(params.domain)}`
    );
    return { detail, error: null as string | null };
  } catch (e) {
    return { detail: null, error: (e as Error).message };
  }
};
