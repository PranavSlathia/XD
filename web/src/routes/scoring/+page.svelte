<script lang="ts">
  import { API_BASE } from '$lib/api';
  import type { PageData } from './$types';
  export let data: PageData;

  let weights: Record<string, number> = data.weights
    ? ((data.weights as any).weights_json as Record<string, number>)
    : {};
  let status = '';

  async function save() {
    const res = await fetch(`${API_BASE}/api/scoring-weights`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ weights_json: weights, notes: 'tuned from dashboard' })
    });
    status = res.ok ? `saved v${((await res.json()) as any).version}` : `failed ${res.status}`;
  }
</script>

<h1 class="text-2xl font-semibold mb-4">Scoring weights</h1>
{#if data.error}
  <p class="text-red-400 text-sm">API unreachable: {data.error}</p>
{:else}
  <p class="text-sm text-zinc-400 mb-4">
    Current version: <span class="font-mono">v{(data.weights as any).version}</span>
  </p>
  <div class="grid gap-4 max-w-xl">
    {#each Object.keys(weights) as key}
      <label class="grid gap-1">
        <span class="text-xs uppercase tracking-wider text-zinc-400">{key}</span>
        <input
          type="range"
          min="-1"
          max="1"
          step="0.01"
          bind:value={weights[key]}
        />
        <span class="text-xs text-zinc-500 font-mono">{weights[key]}</span>
      </label>
    {/each}
    <button class="px-3 py-1 rounded bg-emerald-600 hover:bg-emerald-500 w-fit" on:click={save}>
      Save new version
    </button>
    {#if status}<p class="text-sm text-zinc-400">{status}</p>{/if}
  </div>
{/if}
