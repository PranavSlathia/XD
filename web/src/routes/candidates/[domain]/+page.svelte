<script lang="ts">
  import { API_BASE } from '$lib/api';
  import type { PageData } from './$types';
  export let data: PageData;

  let decisionLog = '';

  async function decide(decision: string) {
    if (!data.detail) return;
    const res = await fetch(`${API_BASE}/api/decisions`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ domain: (data.detail as any).domain, decision })
    });
    decisionLog = res.ok ? `Recorded ${decision}` : `Failed: ${res.status}`;
  }
</script>

{#if data.error || !data.detail}
  <p class="text-red-400 text-sm">{data.error ?? 'not found'}</p>
{:else}
  {@const d = data.detail as any}
  <h1 class="text-2xl font-mono mb-2">{d.domain}</h1>
  <p class="text-sm text-zinc-400 mb-4">
    score {d.composite_score?.toFixed(1) ?? '—'} · {d.current_status ?? 'unknown'} · {d.availability_confidence ?? '—'}
  </p>

  <div class="flex gap-2 mb-6">
    <button class="px-3 py-1 rounded bg-emerald-600 hover:bg-emerald-500" on:click={() => decide('bought')}>Bought</button>
    <button class="px-3 py-1 rounded bg-zinc-700 hover:bg-zinc-600" on:click={() => decide('watching')}>Watching</button>
    <button class="px-3 py-1 rounded bg-zinc-800 hover:bg-zinc-700" on:click={() => decide('passed')}>Pass</button>
    {#if decisionLog}<span class="text-zinc-400 text-sm self-center">{decisionLog}</span>{/if}
  </div>

  <h2 class="text-lg font-semibold mt-6 mb-2">Mentions</h2>
  <ul class="text-sm space-y-1">
    {#each d.mentions ?? [] as m}
      <li><span class="text-zinc-500">{m.context_type}</span> · <a class="text-emerald-300 hover:underline" href={m.source_url} target="_blank" rel="noreferrer">{m.source_url}</a></li>
    {/each}
  </ul>

  <h2 class="text-lg font-semibold mt-6 mb-2">Availability history</h2>
  <ul class="text-sm space-y-1">
    {#each d.availability_history ?? [] as a}
      <li>{a.observed_at?.slice(0, 19)} · {a.source} · {a.status} {a.is_authoritative ? '(auth)' : ''}</li>
    {/each}
  </ul>

  <h2 class="text-lg font-semibold mt-6 mb-2">Wayback</h2>
  <ul class="text-sm space-y-1">
    {#each d.wayback_history ?? [] as w}
      <li>{w.observed_at?.slice(0, 10)} · {w.capture_count} captures</li>
    {/each}
  </ul>
{/if}
