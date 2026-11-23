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
import { CircleAlert, Inbox, LoaderCircle } from "@lucide/vue";

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
  <div v-if="loading" class="state-block" role="status">
    <LoaderCircle class="state-block__loading" :size="18" :stroke-width="1.5" aria-hidden="true" />
    <p>{{ t("app.loading") }}</p>
  </div>

  <div v-else-if="error" class="state-block state-block--error">
    <CircleAlert :size="18" :stroke-width="1.5" aria-hidden="true" />
    <p class="text-danger dark:text-danger-dark">{{ error }}</p>
    <button type="button" class="state-block__button" @click="emit('retry')">
      {{ t("app.retry") }}
    </button>
  </div>

  <div v-else-if="empty" class="state-block">
    <Inbox :size="18" :stroke-width="1.5" aria-hidden="true" />
    <p>{{ emptyText ?? t("app.empty") }}</p>
  </div>

  <slot v-else />
</template>

<style scoped>
.state-block {
  display: flex;
  min-height: 10rem;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  padding: 2rem 1rem;
  border: 0.5px solid var(--kmua-line);
  border-radius: var(--radius-container);
  background: var(--kmua-surface);
  color: var(--kmua-hint);
  text-align: center;
}

.state-block p {
  margin: 0.75rem 0 0;
  font-size: var(--text-sub);
}
.state-block__button {
  margin-top: 0.75rem;
  padding: 0.5rem 1rem;
  border-radius: 0.625rem;
  background: var(--kmua-accent-soft);
  color: var(--kmua-ink);
  font-size: var(--text-sub);
  font-weight: 500;
}
.state-block--error > svg {
  color: var(--color-danger);
}
.state-block__loading {
  animation: state-spin 800ms linear infinite;
}
@keyframes state-spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
