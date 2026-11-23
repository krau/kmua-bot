<script setup lang="ts">
/**
 * Pagination.
 *
 * Two buttons and a count. The label reports the real total rather than a page
 * count, because "12 of 340 items" answers the question people actually have.
 */
import { t } from "@/i18n";
import { haptics } from "@/telegram";

const props = defineProps<{
  page: number;
  size: number;
  total: number;
  loading?: boolean;
}>();

const emit = defineEmits<{ "update:page": [number] }>();

function go(delta: number): void {
  const next = props.page + delta;
  if (next < 1) return;
  if ((next - 1) * props.size >= props.total) return;
  haptics.tap();
  emit("update:page", next);
}
</script>

<template>
  <nav v-if="total > size" class="pager mt-related flex items-center justify-between px-related">
    <button
      type="button"
      class="text-sub disabled:text-hint disabled:opacity-50"
      :class="page > 1 ? 'text-accent dark:text-accent-dark' : ''"
      :disabled="page <= 1 || loading"
      @click="go(-1)"
    >
      {{ t("app.prev") }}
    </button>

    <span class="text-note text-hint tabular-nums">
      {{ t("app.page", { page, total }) }}
    </span>

    <button
      type="button"
      class="text-sub disabled:text-hint disabled:opacity-50"
      :class="page * size < total ? 'text-accent dark:text-accent-dark' : ''"
      :disabled="page * size >= total || loading"
      @click="go(1)"
    >
      {{ t("app.next") }}
    </button>
  </nav>
</template>

<style scoped>
.pager {
  margin-bottom: 1.75rem;
  padding: 0.5rem;
  border: 1px solid var(--kmua-line);
  border-radius: 999px;
  background: var(--kmua-surface);
}

.pager button {
  padding: 0.45rem 0.875rem;
  border-radius: 999px;
  font-weight: 800;
}
.pager button:not(:disabled):hover {
  background: var(--kmua-mint-soft);
}
.pager > span {
  font-size: 0.75rem;
  font-weight: 700;
}
</style>
