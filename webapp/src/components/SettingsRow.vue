<script setup lang="ts">
/**
 * One row in a settings group.
 *
 * A row is a label, an optional value, and one control. No icon: an icon per row
 * would be decoration that has to be invented for each setting, and invented icons
 * do not help anybody find "AI reply".
 *
 * Rendered as a `<button>` only when it actually navigates or acts, so screen
 * readers and keyboards get a real control and static rows stay static.
 */
import { computed } from "vue";

import ActivityDot from "@/components/ActivityDot.vue";
import { haptics } from "@/telegram";

const props = withDefaults(
  defineProps<{
    label: string;
    /** Right-aligned secondary value. */
    value?: string | number | null;
    /** One line under the label, for the few settings that need explaining. */
    hint?: string;
    /** Show a chevron and make the row tappable. */
    navigable?: boolean;
    disabled?: boolean;
    /** Render the label in the danger colour, for destructive actions. */
    destructive?: boolean;
    /** Show a change marker: this row has an unsaved edit. */
    changed?: boolean;
    /** Use a monospace value, for ids and other identifiers. */
    mono?: boolean;
    /**
     * This row's action is in flight.
     *
     * Some actions take a noticeable moment - refreshing an avatar re-downloads it from
     * Telegram, syncing members walks the whole roster. Without this the row looked
     * inert and the only feedback arrived seconds later, so people tapped again.
     */
    busy?: boolean;
  }>(),
  {
    value: null,
    navigable: false,
    disabled: false,
    destructive: false,
    changed: false,
    mono: false,
    busy: false,
  },
);

const emit = defineEmits<{ click: [] }>();

/** Busy implies disabled: a second tap while the first is in flight is never wanted. */
const inert = computed(() => props.disabled || props.busy);

/**
 * The listener is bound unconditionally and gates here instead.
 *
 * A conditional handler expression on `<component :is>` makes vue-tsc resolve the
 * emit's own name in template scope, which does not exist. Gating in the function is
 * both simpler and the same behaviour: a static row never reaches the emit.
 */
function onActivate(): void {
  if (!props.navigable || inert.value) return;
  haptics.tap();
  emit("click");
}
</script>

<template>
  <!--
    A busy row keeps full opacity. Dimming it would say it is unavailable, when what is
    true is that it is working - so only a genuinely disabled row is dimmed, and the
    spinner carries the busy state instead.
  -->
  <component
    :is="navigable ? 'button' : 'div'"
    :type="navigable ? 'button' : undefined"
    :disabled="navigable && inert ? true : undefined"
    :aria-busy="busy ? 'true' : undefined"
    class="border-line flex w-full items-center gap-related border-b px-related py-related text-left last:border-b-0"
    :class="[
      navigable && !inert
        ? 'active:bg-ink/5 dark:active:bg-ink/10 transition-colors duration-150 ease-out'
        : '',
      /* Busy rows keep full opacity - see the note above the element. */
      disabled && !busy ? 'opacity-50' : '',
      /*
        A 2px accent bar means this field has an unsaved edit. It is a real signal,
        not the decorative coloured left border that docs admonitions turned into a
        universal ornament.
      */
      changed ? 'border-l-accent dark:border-l-accent-dark border-l-2 pl-[calc(1rem-2px)]' : '',
    ]"
    @click="navigable ? onActivate() : undefined"
  >
    <span class="min-w-0 flex-1">
      <span class="block text-body" :class="destructive ? 'text-danger dark:text-danger-dark' : ''">
        {{ label }}
      </span>
      <span v-if="hint" class="mt-1 block text-note text-hint">{{ hint }}</span>
    </span>

    <span
      v-if="value !== null && value !== undefined && !busy"
      class="text-sub text-hint shrink-0"
      :class="mono ? 'font-mono' : ''"
    >
      {{ value }}
    </span>

    <slot name="control" />

    <!--
      While busy, a spinner replaces the chevron in the same slot: the row keeps its
      geometry, so nothing reflows when the action starts or finishes.
    -->
    <ActivityDot v-if="busy" class="shrink-0" />
    <span v-else-if="navigable" class="text-hint shrink-0 text-sub" aria-hidden="true">›</span>
  </component>
</template>
