<script lang="ts">
  import type { PageData } from './$types';
  export let data: PageData;
</script>

<h1 class="text-2xl font-semibold mb-4">Today's digest</h1>
{#if data.error}
  <p class="text-red-400 text-sm">API unreachable: {data.error}</p>
{:else if data.items.length === 0}
  <p class="text-zinc-400 text-sm">No candidates met the digest gate today.</p>
{:else}
  <ul class="grid gap-3">
    {#each data.items as item}
      <li class="border border-zinc-800 rounded-lg px-4 py-3 flex items-baseline justify-between">
        <a href={`/candidates/${item.domain}`} class="font-mono text-emerald-300 hover:underline">
          {item.domain}
        </a>
        <span class="text-sm text-zinc-400">
          score {item.composite_score?.toFixed(1) ?? '—'} · {item.current_status ?? 'unknown'}
        </span>
      </li>
    {/each}
  </ul>
{/if}
