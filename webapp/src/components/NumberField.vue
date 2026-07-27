<script setup lang="ts">
/**
 * An integer field.
 *
 * Kept separate from TextField because a numeric `v-model` needs its own parsing: an
 * empty or half-typed input must not become `NaN` and silently submit garbage, so a
 * blank box reads as 0 and non-numeric input is ignored.
 *
 * Shares `.field-input` with the other fields: a tinted dent in the row rather than an
 * underline, which in a grouped list would double up with the row separator below it.
 */
withDefaults(
  defineProps<{
    modelValue: number;
    label: string;
    hint?: string;
    min?: number;
    max?: number;
    changed?: boolean;
    disabled?: boolean;
  }>(),
  { changed: false, disabled: false },
);

const emit = defineEmits<{ "update:modelValue": [number] }>();

const inputId = `number-${Math.random().toString(36).slice(2, 9)}`;

function onInput(event: Event): void {
  const raw = (event.target as HTMLInputElement).value.trim();
  if (raw === "" || raw === "-") {
    emit("update:modelValue", 0);
    return;
  }
  const parsed = Number(raw);
  if (Number.isFinite(parsed)) emit("update:modelValue", Math.trunc(parsed));
}
</script>

<template>
  <div
    class="border-line flex items-center gap-related border-b px-related py-related last:border-b-0"
    :class="
      changed ? 'border-l-accent dark:border-l-accent-dark border-l-2 pl-[calc(1rem-2px)]' : ''
    "
  >
    <label :for="inputId" class="min-w-0 flex-1">
      <span class="block text-body">{{ label }}</span>
      <span v-if="hint" class="mt-1 block text-note text-hint">{{ hint }}</span>
    </label>
    <input
      :id="inputId"
      :value="modelValue"
      :min="min"
      :max="max"
      :disabled="disabled"
      type="number"
      inputmode="numeric"
      class="field-input w-32 shrink-0 text-right text-body tabular-nums"
      @input="onInput"
    />
  </div>
</template>

<style scoped>
/* The native spinners are too small to hit reliably and the value is typed. */
input[type="number"]::-webkit-inner-spin-button,
input[type="number"]::-webkit-outer-spin-button {
  appearance: none;
  margin: 0;
}
input[type="number"] {
  appearance: textfield;
}
</style>
