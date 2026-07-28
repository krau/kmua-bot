<script setup lang="ts">
/**
 * Loading, empty and error states.
 *
 * One component so all three read the same everywhere. Deliberately plain text -
 * no spinner, no illustration, no coloured alert box. A one-line message in hint
 * colour says what happened; a rounded amber callout with an icon would dress up
 * "nothing here" as an event.
 */
import { t } from "@/i18n";

withDefaults(
  defineProps<{
    loading?: boolean;
    error?: string | null;
    /** True when loading finished and there is nothing to show. */
    empty?: boolean;
    emptyText?: string;
  }>(),
  { loading: false, error: null, empty: false, emptyText: undefined },
);

const emit = defineEmits<{ retry: [] }>();
</script>

<template>
  <p v-if="loading" class="px-related py-related text-sub text-hint">{{ t("app.loading") }}</p>

  <div v-else-if="error" class="px-related py-related">
    <p class="text-sub text-danger dark:text-danger-dark">{{ error }}</p>
    <button
      type="button"
      class="text-accent dark:text-accent-dark mt-tight text-sub underline"
      @click="emit('retry')"
    >
      {{ t("app.retry") }}
    </button>
  </div>

  <p v-else-if="empty" class="px-related py-related text-sub text-hint">
    {{ emptyText ?? t("app.empty") }}
  </p>

  <slot v-else />
</template>
