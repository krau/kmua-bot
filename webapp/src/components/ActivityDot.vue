<script setup lang="ts">
/**
 * A small spinner for an action in flight.
 *
 * Sized and coloured to sit where the chevron sits in a settings row, so swapping one
 * for the other changes nothing about the row's geometry.
 *
 * A rotating arc rather than pulsing dots or a progress bar: the duration is unknown,
 * so anything implying progress would be lying, and three staggered dots is more motion
 * than a row needs. Drawn in `currentColor` at hint weight - it reports state, it is
 * not an accent.
 *
 * `prefers-reduced-motion` is honoured globally in main.css, which collapses the
 * animation. The arc is still visible, so the row is not left looking idle.
 */
defineProps<{
  /** Accessible label. Omit inside a row that already carries aria-busy. */
  label?: string;
}>();
</script>

<template>
  <span
    class="activity-dot text-hint"
    :role="label ? 'status' : undefined"
    :aria-label="label"
    :aria-hidden="label ? undefined : 'true'"
  />
</template>

<style scoped>
.activity-dot {
  display: inline-block;
  width: 0.875rem;
  height: 0.875rem;
  border: 2px solid currentColor;
  border-radius: 50%;
  /* One transparent quarter is what makes the rotation legible. */
  border-top-color: transparent;
  opacity: 0.7;
  animation: activity-spin 700ms linear infinite;
}

@keyframes activity-spin {
  to {
    rotate: 360deg;
  }
}
</style>
