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
import { CircleAlert, Flower2, Inbox } from "@lucide/vue";

withDefaults(
  defineProps<{
    loading?: boolean;
    loadingLabel?: string;
    /** Render stable page fields while their values load. */
    loadingContent?: boolean;
    error?: string | null;
    /** True when loading finished and there is nothing to show. */
    empty?: boolean;
    emptyText?: string;
  }>(),
  {
    loading: false,
    loadingLabel: undefined,
    loadingContent: false,
    error: null,
    empty: false,
    emptyText: undefined,
  },
);

const emit = defineEmits<{ retry: [] }>();
</script>

<template>
  <section
    v-if="loading && !loadingContent"
    class="settings-section"
    role="status"
    :aria-label="t('app.loading')"
  >
    <div v-if="loadingLabel" class="settings-section__heading">
      <h2><Flower2 :size="16" :stroke-width="1.5" aria-hidden="true" />{{ loadingLabel }}</h2>
    </div>
    <div class="state-block state-block--loading">
      <span class="sr-only">{{ t("app.loading") }}</span>
      <div class="state-skeleton" aria-hidden="true">
        <div v-for="row in 3" :key="row" class="state-skeleton__row">
          <span class="state-skeleton__label" />
          <span class="state-skeleton__value" />
        </div>
      </div>
    </div>
  </section>

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

  <div v-else class="state-content" :aria-busy="loading ? 'true' : undefined">
    <span v-if="loading" class="sr-only" role="status">{{ t("app.loading") }}</span>
    <slot />
  </div>
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
.state-block--loading {
  display: block;
  min-height: 0;
  padding: 0;
  box-shadow: var(--kmua-shadow);
}

.state-skeleton__row {
  display: flex;
  min-height: 3rem;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  padding-inline: 1rem;
  border-bottom: 0.5px solid var(--kmua-line);
}

.state-skeleton__row:last-child {
  border-bottom: 0;
}
.state-skeleton__label,
.state-skeleton__value {
  display: block;
  height: 0.75rem;
  border-radius: 0.25rem;
  background: var(--kmua-bg);
}

.state-skeleton__label {
  width: 42%;
}
.state-skeleton__value {
  width: 18%;
}
.state-skeleton__row:nth-child(2) .state-skeleton__label {
  width: 56%;
}
.state-skeleton__row:nth-child(3) .state-skeleton__label {
  width: 34%;
}
</style>
