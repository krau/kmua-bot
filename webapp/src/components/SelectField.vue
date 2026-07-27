<script setup lang="ts">
/**
 * A choice among a short list, rendered as a native `<select>`.
 *
 * Native is the right primitive: on a phone Telegram hands it to the OS picker,
 * which is faster to use and accessible for free, and on any platform it behaves the
 * way a select is expected to - one row that opens, not a list that grows.
 *
 * What is fixed here is the look. The default control draws the browser's own arrow
 * and, on desktop, a white dropdown with its own borders and blue highlight, which
 * ignores the Telegram theme entirely. So the button itself is stripped
 * (`appearance: none`) and rebuilt to match a settings row: value in hint colour on
 * the right, our own chevron after it, sized and coloured from the design tokens.
 *
 * The dropdown itself is only stylable where `appearance: base-select` is supported,
 * so that lives in a `@supports` block: browsers that have it get a themed picker,
 * the rest keep the OS one. The row looks identical either way, which is the part
 * the user actually sees while the panel is idle.
 */
withDefaults(
  defineProps<{
    modelValue: string;
    label: string;
    options: readonly { value: string; text: string }[];
    hint?: string;
    changed?: boolean;
    disabled?: boolean;
  }>(),
  { changed: false, disabled: false },
);

defineEmits<{ "update:modelValue": [string] }>();

const inputId = `select-${Math.random().toString(36).slice(2, 9)}`;
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

    <!--
      The chevron is a sibling rather than a background-image on the select: it has to
      take its colour from the same token as the value text, and a background-image
      cannot follow `currentColor` through a theme switch.
    -->
    <div
      class="text-sub text-hint flex shrink-0 items-center gap-1"
      :class="disabled ? 'opacity-50' : ''"
    >
      <select
        :id="inputId"
        :value="modelValue"
        :disabled="disabled"
        class="field-select cursor-pointer bg-transparent py-1 text-right outline-none disabled:cursor-not-allowed"
        @change="$emit('update:modelValue', ($event.target as HTMLSelectElement).value)"
      >
        <option v-for="option in options" :key="option.value" :value="option.value">
          {{ option.text }}
        </option>
      </select>
      <span class="field-select-chevron text-note" aria-hidden="true">⌄</span>
    </div>
  </div>
</template>

<style scoped>
.field-select {
  /* Strip the platform arrow and padding; the row supplies both. */
  appearance: none;
  border: none;
  padding-right: 0;
  /* Long language names must not push the label off the row. */
  max-width: 14rem;
  text-overflow: ellipsis;
}

.field-select-chevron {
  /* Optical alignment: the glyph sits high in its box. */
  translate: 0 -0.15em;
}

/*
  Where the picker is stylable, theme it and hand the arrow back to the control.
  Everything here is Telegram's own palette, so an open dropdown belongs to the same
  surface as the list behind it.
*/
@supports (appearance: base-select) {
  .field-select,
  .field-select::picker(select) {
    appearance: base-select;
  }

  .field-select {
    /* The native control draws its own icon under base-select. */
    padding-right: 0.25rem;
  }

  .field-select-chevron {
    display: none;
  }

  .field-select::picker-icon {
    color: var(--color-hint);
    transition: rotate 150ms ease-out;
  }

  .field-select:open::picker-icon {
    rotate: 180deg;
  }

  .field-select::picker(select) {
    border: 1px solid var(--color-line);
    border-radius: var(--radius-container);
    background-color: var(--color-bg);
    padding: 0;
    /* No shadow: separation is a hairline here, as everywhere else in the panel. */
    overflow: hidden;
  }

  .field-select option {
    display: flex;
    align-items: center;
    gap: var(--spacing-tight);
    padding: 0.625rem var(--spacing-related);
    color: var(--color-ink);
    font-size: var(--text-body);
    text-align: left;
  }

  .field-select option:not(:last-child) {
    border-bottom: 1px solid var(--color-line);
  }

  .field-select option:hover,
  .field-select option:focus {
    background-color: var(--color-surface);
    /* The OS highlight colour has no relationship to the user's Telegram theme. */
    color: var(--color-ink);
  }

  .field-select option::checkmark {
    order: 1;
    margin-left: auto;
    color: var(--color-accent);
    font-size: var(--text-sub);
  }

  :global([data-theme="dark"]) .field-select option::checkmark {
    color: var(--color-accent-dark);
  }
}
</style>
