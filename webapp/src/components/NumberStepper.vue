<script setup lang="ts">
/**
 * A numeric field with a labelled unit.
 *
 * Used for the random-quote probability, which is a percentage the user thinks
 * about in tenths but the API stores as a 0..1 float. The conversion lives here so
 * the page never juggles both representations.
 */
import { computed } from "vue";

const props = withDefaults(
  defineProps<{
    /** Stored value, 0..1. */
    modelValue: number;
    /** Step in displayed percentage points. */
    step?: number;
    min?: number;
    max?: number;
    label: string;
    hint?: string;
  }>(),
  { step: 0.1, min: 0, max: 100 },
);

const emit = defineEmits<{ "update:modelValue": [number] }>();

const percent = computed({
  get: () => Number((props.modelValue * 100).toFixed(3)),
  set: (value: number) => {
    const clamped = Math.min(props.max, Math.max(props.min, value));
    // Round-trip through a fixed precision so 0.1% does not become 0.0999999.
    emit("update:modelValue", Number((clamped / 100).toFixed(5)));
  },
});

const inputId = `stepper-${Math.random().toString(36).slice(2, 9)}`;
</script>

<template>
  <div
    class="border-line flex items-center gap-related border-b px-related py-related last:border-b-0"
  >
    <label :for="inputId" class="min-w-0 flex-1">
      <span class="block text-body">{{ label }}</span>
      <span v-if="hint" class="mt-1 block text-note text-hint">{{ hint }}</span>
    </label>
    <div class="flex shrink-0 items-baseline gap-1">
      <input
        :id="inputId"
        v-model.number="percent"
        type="number"
        inputmode="decimal"
        :step="step"
        :min="min"
        :max="max"
        class="field-input w-20 text-right text-body tabular-nums"
      />
      <span class="text-sub text-hint">%</span>
    </div>
  </div>
</template>

<style scoped>
/* The native spinners are too small to hit on a phone and the value is typed. */
input[type="number"]::-webkit-inner-spin-button,
input[type="number"]::-webkit-outer-spin-button {
  appearance: none;
  margin: 0;
}
input[type="number"] {
  appearance: textfield;
}
</style>
