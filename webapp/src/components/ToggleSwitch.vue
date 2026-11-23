<script setup lang="ts">
/**
 * A toggle.
 *
 * A real `<button role="switch">`, not a styled div: it is reachable by keyboard,
 * announces its state, and works with a screen reader. The engaged colour is the
 * single accent - one of only three places it appears.
 *
 * Only the properties that change are transitioned. `transition-all` plus
 * `hover:scale` is the reflex here, and both are wrong: hover does not exist on
 * touch, and a switch does not grow when you flip it.
 */
import { haptics } from "@/telegram";

const props = withDefaults(
  defineProps<{
    modelValue: boolean;
    disabled?: boolean;
    /** Accessible name, when the visible label lives outside this component. */
    ariaLabel?: string;
    /** In-flight server write: the knob becomes a spinner and taps are ignored. */
    busy?: boolean;
  }>(),
  { disabled: false, ariaLabel: undefined, busy: false },
);

const emit = defineEmits<{ "update:modelValue": [boolean] }>();

function toggle(): void {
  if (props.disabled || props.busy) return;
  haptics.tap();
  emit("update:modelValue", !props.modelValue);
}
</script>

<template>
  <button
    type="button"
    role="switch"
    :aria-checked="modelValue"
    :aria-label="ariaLabel"
    :disabled="disabled"
    class="toggle-switch relative shrink-0 rounded-full transition-colors duration-150 ease-out"
    :class="[
      modelValue ? 'bg-accent dark:bg-accent-dark' : 'bg-hint/35',
      disabled ? 'cursor-not-allowed opacity-50' : '',
    ]"
    @click.stop="toggle"
  >
    <span class="toggle-switch__knob absolute block rounded-full bg-white">
      <span
        v-if="busy"
        class="block h-full w-full rounded-full animate-spin border-2 border-hint border-t-accent"
      />
    </span>
  </button>
</template>

<style scoped>
.toggle-switch {
  width: 3.25rem;
  height: 2rem;
  border: 0;
}

.toggle-switch[aria-checked="true"] {
  background: var(--kmua-mint) !important;
}

.toggle-switch__knob {
  top: 0.25rem;
  left: 0.25rem;
  width: 1.5rem;
  height: 1.5rem;
  transform: translateX(0);
  transition: transform var(--duration-quick, 150ms) ease-out;
}

.toggle-switch[aria-checked="true"] .toggle-switch__knob {
  transform: translateX(1.25rem);
}
</style>
