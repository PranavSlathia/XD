<script lang="ts">
  import type { PageData } from './$types';
  export let data: PageData;
</script>

<h1 class="text-2xl font-semibold mb-4">Candidates</h1>
{#if data.error}
  <p class="text-red-400 text-sm">API unreachable: {data.error}</p>
{:else}
  <table class="w-full text-sm">
    <thead class="text-left text-zinc-500 border-b border-zinc-800">
      <tr>
        <th class="py-2">domain</th>
        <th>score</th>
        <th>status</th>
        <th>confidence</th>
      </tr>
    </thead>
    <tbody>
      {#each data.items as c}
        <tr class="border-b border-zinc-900">
          <td class="py-2">
            <a href={`/candidates/${c.domain}`} class="font-mono text-emerald-300 hover:underline">
              {c.domain}
            </a>
          </td>
          <td>{c.composite_score?.toFixed(1) ?? '—'}</td>
          <td>{c.current_status ?? '—'}</td>
          <td>{c.availability_confidence ?? '—'}</td>
        </tr>
      {/each}
    </tbody>
  </table>
{/if}
