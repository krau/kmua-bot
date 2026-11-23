<script setup lang="ts">
import { Flower2 } from "@lucide/vue";

defineProps<{
  label?: string;
  hint?: string;
}>();

const headingId = `section-${Math.random().toString(36).slice(2, 9)}`;
</script>

<template>
  <section class="settings-section" :aria-labelledby="label ? headingId : undefined">
    <div v-if="label || hint" class="settings-section__heading">
      <h2 v-if="label" :id="headingId">
        <Flower2 :size="16" :stroke-width="1.5" aria-hidden="true" />{{ label }}
      </h2>
      <p v-if="hint">{{ hint }}</p>
    </div>
    <div class="settings-section__body">
      <slot />
    </div>
  </section>
</template>
