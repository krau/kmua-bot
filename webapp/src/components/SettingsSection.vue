<script setup lang="ts">
defineProps<{
  label?: string;
  hint?: string;
}>();

const headingId = `section-${Math.random().toString(36).slice(2, 9)}`;
</script>

<template>
  <section class="settings-section" :aria-labelledby="label ? headingId : undefined">
    <div v-if="label || hint" class="settings-section__heading">
      <h2 v-if="label" :id="headingId"><span aria-hidden="true">✿</span>{{ label }}</h2>
      <p v-if="hint">{{ hint }}</p>
    </div>
    <div class="settings-section__body">
      <slot />
    </div>
  </section>
</template>
