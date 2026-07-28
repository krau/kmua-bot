<script setup lang="ts">
/**
 * A group of related rows.
 *
 * The panel is a settings list, not a card grid: sixteen unordered toggles laid out
 * as sixteen equal cards would fake a structure that is not there. A grouped list
 * says what belongs with what through proximity and a single hairline.
 *
 * The group label is small hint-coloured text, not an all-caps letter-spaced
 * kicker: it names the group, it is not a badge.
 */
defineProps<{
  /** Group label. Omit for a group that needs no name. */
  label?: string;
  /** One line of explanation under the label, only where it earns its place. */
  hint?: string;
}>();

const headingId = `section-${Math.random().toString(36).slice(2, 9)}`;
</script>

<template>
  <section class="mb-section" :aria-labelledby="label ? headingId : undefined">
    <h2 v-if="label" :id="headingId" class="mb-tight px-related text-note text-hint">
      {{ label }}
    </h2>
    <p v-if="hint" class="mb-tight px-related text-note text-hint">{{ hint }}</p>
    <div class="bg-surface rounded-container overflow-hidden">
      <slot />
    </div>
  </section>
</template>
