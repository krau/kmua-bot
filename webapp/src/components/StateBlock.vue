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
  <div v-if="loading" class="state-block" role="status">
    <span class="state-block__mascot" aria-hidden="true">=^･ω･^=</span>
    <span class="state-block__dots" aria-hidden="true"><i /><i /><i /></span>
    <p>{{ t("app.loading") }}</p>
  </div>

  <div v-else-if="error" class="state-block state-block--error">
    <span class="state-block__mascot" aria-hidden="true">=^；ω；^=</span>
    <p class="text-danger dark:text-danger-dark">{{ error }}</p>
    <button type="button" class="state-block__button" @click="emit('retry')">
      {{ t("app.retry") }}
    </button>
  </div>

  <div v-else-if="empty" class="state-block">
    <span class="state-block__mascot" aria-hidden="true">=^･ω･^=</span>
    <p>{{ emptyText ?? t("app.empty") }}</p>
    <span class="state-block__note" aria-hidden="true">♡ · ｡ ﾟ</span>
  </div>

  <slot v-else />
</template>

<style scoped>
.state-block {
  display: flex;
  min-height: 12rem;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  padding: 2rem 1rem;
  border: 1.5px dashed var(--kmua-line);
  border-radius: var(--radius-container);
  background: color-mix(in srgb, var(--kmua-surface) 65%, transparent);
  color: var(--kmua-hint);
  text-align: center;
}

.state-block__mascot {
  color: var(--kmua-pink);
  font-size: 1.5rem;
  font-weight: 900;
  letter-spacing: 0.03em;
}
.state-block p {
  margin: 0.75rem 0 0;
  font-size: var(--text-sub);
}
.state-block__dots {
  display: flex;
  gap: 0.25rem;
  margin-top: 0.75rem;
}
.state-block__dots i {
  width: 0.35rem;
  height: 0.35rem;
  border-radius: 50%;
  background: var(--kmua-mint);
  animation: dot-hop 900ms ease-in-out infinite;
}
.state-block__dots i:nth-child(2) {
  animation-delay: 120ms;
}
.state-block__dots i:nth-child(3) {
  animation-delay: 240ms;
}
.state-block__button {
  margin-top: 0.875rem;
  padding: 0.45rem 1rem;
  border-radius: 999px;
  background: var(--kmua-pink-soft);
  color: var(--kmua-ink);
  font-size: var(--text-sub);
  font-weight: 800;
}
.state-block__note {
  margin-top: 0.5rem;
  color: var(--kmua-mint);
}
@keyframes dot-hop {
  50% {
    translate: 0 -4px;
  }
}
</style>
