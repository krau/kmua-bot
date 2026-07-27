<script setup lang="ts">
/**
 * A multi-line text field, used for the group greeting.
 *
 * Auto-grows rather than scrolling inside a fixed box: a greeting is usually two or
 * three lines and being able to see all of it matters more than a stable page
 * height.
 */
withDefaults(
  defineProps<{
    modelValue: string;
    label: string;
    hint?: string;
    placeholder?: string;
    maxlength?: number;
    changed?: boolean;
  }>(),
  { changed: false },
);

defineEmits<{ "update:modelValue": [string] }>();

const inputId = `area-${Math.random().toString(36).slice(2, 9)}`;
</script>

<template>
  <div
    class="border-line border-b px-related py-related last:border-b-0"
    :class="
      changed ? 'border-l-accent dark:border-l-accent-dark border-l-2 pl-[calc(1rem-2px)]' : ''
    "
  >
    <label :for="inputId" class="block text-body">{{ label }}</label>
    <p v-if="hint" class="mt-1 text-note text-hint">{{ hint }}</p>
    <textarea
      :id="inputId"
      :value="modelValue"
      :placeholder="placeholder"
      :maxlength="maxlength"
      rows="3"
      class="field-input mt-tight field-sizing-content resize-none text-body"
      @input="$emit('update:modelValue', ($event.target as HTMLTextAreaElement).value)"
    />
    <p v-if="maxlength" class="mt-1 text-right text-note text-hint tabular-nums">
      {{ modelValue.length }} / {{ maxlength }}
    </p>
  </div>
</template>
