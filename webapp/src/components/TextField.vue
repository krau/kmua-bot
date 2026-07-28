<script setup lang="ts">
/**
 * A single-line text field inside a settings group.
 *
 * Matches SettingsRow's geometry so a group can mix toggles and inputs without the
 * rows drifting out of alignment.
 *
 * The box is a tinted dent in the row (`.field-input`), not an underline: an
 * underlined input in a grouped list puts its own hairline a few pixels above the row
 * separator, and the pair reads as one doubled line rather than as an editable field.
 */
withDefaults(
  defineProps<{
    modelValue: string;
    label: string;
    hint?: string;
    placeholder?: string;
    maxlength?: number;
    inputmode?: "text" | "numeric" | "decimal" | "search";
    changed?: boolean;
    disabled?: boolean;
  }>(),
  { inputmode: "text", changed: false, disabled: false },
);

defineEmits<{ "update:modelValue": [string] }>();

const inputId = `field-${Math.random().toString(36).slice(2, 9)}`;
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
    <input
      :id="inputId"
      :value="modelValue"
      :placeholder="placeholder"
      :maxlength="maxlength"
      :inputmode="inputmode"
      :disabled="disabled"
      type="text"
      class="field-input mt-tight text-body"
      @input="$emit('update:modelValue', ($event.target as HTMLInputElement).value)"
    />
  </div>
</template>
