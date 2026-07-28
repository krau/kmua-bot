<script setup lang="ts">
/**
 * Label-value pairs.
 *
 * The developer panel's numbers (users, chats, quotes, memberships, bottles) are
 * real measurements, so they are shown as a compact list with the values aligned -
 * not as a row of big numbers in separate cards. A stat-card grid would give five
 * unrelated counters equal visual weight and imply a hierarchy that does not exist.
 *
 * Values are tabular so figures line up and do not jitter on refresh.
 */
export interface DefinitionItem {
  label: string;
  value: string | number;
  /** Render as monospace: ids, hashes, config keys. */
  mono?: boolean;
  /** Render muted, e.g. "not set". */
  muted?: boolean;
}

defineProps<{ items: DefinitionItem[] }>();
</script>

<template>
  <dl class="m-0">
    <div
      v-for="item in items"
      :key="item.label"
      class="border-line flex items-baseline gap-related border-b px-related py-tight last:border-b-0"
    >
      <dt class="text-hint min-w-0 flex-1 text-sub">{{ item.label }}</dt>
      <dd
        class="m-0 shrink-0 text-body tabular-nums"
        :class="[item.mono ? 'font-mono text-sub' : '', item.muted ? 'text-hint' : '']"
      >
        {{ item.value }}
      </dd>
    </div>
  </dl>
</template>
