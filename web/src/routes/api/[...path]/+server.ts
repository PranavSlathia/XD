import { env } from '$env/dynamic/private';
import type { RequestHandler } from './$types';

const INTERNAL_API_BASE = env.DH_INTERNAL_API_BASE_URL ?? 'http://dh-api:8000';

async function proxy({ params, request, url, fetch }: Parameters<RequestHandler>[0]): Promise<Response> {
  const target = new URL(`/api/${params.path ?? ''}${url.search}`, INTERNAL_API_BASE);
  const headers = new Headers(request.headers);
  headers.delete('host');

  const init: RequestInit = {
    method: request.method,
    headers,
    body: request.method === 'GET' || request.method === 'HEAD' ? undefined : request.body,
    duplex: 'half'
  } as RequestInit;

  return fetch(target, init);
}

export const GET: RequestHandler = proxy;
export const POST: RequestHandler = proxy;
export const PUT: RequestHandler = proxy;
export const PATCH: RequestHandler = proxy;
export const DELETE: RequestHandler = proxy;
