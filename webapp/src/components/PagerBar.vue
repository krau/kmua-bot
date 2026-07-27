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
  <nav v-if="total > size" class="mt-related flex items-center justify-between px-related">
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
