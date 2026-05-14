# Domain Hunter — Web Dashboard

SvelteKit 5 + Tailwind v4 + Melt UI + Bits UI + TanStack Table + ECharts.
Tailscale-only (no auth). Talks to `dh-api` over the in-cluster network.

## Develop locally

```bash
cd web
npm install
PUBLIC_DH_API_BASE_URL=http://127.0.0.1:8004 npm run dev
```

## Build

```bash
npm run build
```

## Docker

Built as the `dh-web` service (compose profile `web`).

## Env

| Var | Default | Notes |
|---|---|---|
| `PUBLIC_DH_API_BASE_URL` | `http://dh-api:8000` | Used by both `+page.server.ts` (server-side fetches) and the in-browser SSE client. |
