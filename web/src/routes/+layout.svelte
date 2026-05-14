<script lang="ts">
  import '../app.css';
  import { onMount } from 'svelte';
  import { startEventStream } from '$lib/events';

  onMount(() => startEventStream());
</script>

<header class="border-b border-zinc-800 px-6 py-4 flex gap-6 items-baseline">
  <a href="/" class="text-lg font-semibold tracking-tight">Domain Hunter</a>
  <nav class="flex gap-4 text-sm text-zinc-400">
    <a href="/" class="hover:text-zinc-100">Digest</a>
    <a href="/candidates" class="hover:text-zinc-100">Candidates</a>
    <a href="/scoring" class="hover:text-zinc-100">Scoring</a>
  </nav>
</header>

<main class="px-6 py-6">
  <slot />
</main>
