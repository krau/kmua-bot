<script setup lang="ts">
/**
 * The page title.
 *
 * Appears once per page and names the one thing the page is about. There is no
 * kicker above it: a tiny all-caps label restating the heading adds no information
 * and is a template's rhythm rather than a decision.
 */
defineProps<{
  title: string;
  /** Optional context under the title, e.g. which group is being edited. */
  subtitle?: string;
}>();
</script>

<template>
  <header class="mb-section px-related">
    <h1 class="text-display font-semibold">{{ title }}</h1>
    <p v-if="subtitle" class="mt-tight text-sub text-hint">{{ subtitle }}</p>
  </header>
</template>
