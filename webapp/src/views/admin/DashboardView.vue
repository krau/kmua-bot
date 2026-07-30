<script setup lang="ts">
/**
 * Developer panel home: the counters, plus links to the rest.
 *
 * The counters are shown as an aligned definition list, not as five big numbers in
 * separate cards. They are real measurements of unrelated things, and a stat-card row
 * would give them equal visual weight while implying they belong together.
 */
import { computed, onBeforeUnmount, onMounted } from "vue";
import { useRouter } from "vue-router";

import { fetchStats } from "@/api/endpoints/admin";
import DefinitionList, { type DefinitionItem } from "@/components/DefinitionList.vue";
import PageHeader from "@/components/PageHeader.vue";
import SettingsRow from "@/components/SettingsRow.vue";
import SettingsSection from "@/components/SettingsSection.vue";
import StateBlock from "@/components/StateBlock.vue";
import { useAsyncData } from "@/composables/useAsyncData";
import { t } from "@/i18n";
import { useSessionStore } from "@/stores/session";
import { formatNumber } from "@/utils/format";

const router = useRouter();
const session = useSessionStore();

const stats = useAsyncData((signal) => fetchStats(signal));

const counters = computed<DefinitionItem[]>(() => {
  const data = stats.data.value;
  if (!data) return [];
  return [
    { label: t("admin.users"), value: formatNumber(data.users) },
    { label: t("admin.chats"), value: formatNumber(data.chats) },
    { label: t("admin.quotes"), value: formatNumber(data.quotes) },
    { label: t("admin.associations"), value: formatNumber(data.associations) },
    { label: t("admin.bottles"), value: formatNumber(data.bottles) },
  ];
});

const affection = computed<DefinitionItem[]>(() => {
  const data = stats.data.value?.affection;
  if (!data) return [];
  const items: DefinitionItem[] = [];
  if (data.bucket_count !== undefined) {
    items.push({ label: t("admin.affectionBuckets"), value: formatNumber(data.bucket_count) });
  }
  if (data.min_bucket !== undefined && data.max_bucket !== undefined) {
    items.push({
      label: t("admin.affectionRange"),
      value: `${data.min_bucket} … ${data.max_bucket}`,
      mono: true,
    });
  }
  return items;
});

const activity = computed<DefinitionItem[]>(() => {
  const data = stats.data.value?.dashboard;
  if (!data) return [];
  return [
    { label: t("admin.realUsers"), value: formatNumber(data.user_structure.real_users ?? 0) },
    { label: t("admin.marriedUsers"), value: formatNumber(data.user_structure.married_users ?? 0) },
    { label: t("admin.quotesWeek"), value: formatNumber(data.recent.quotes ?? 0) },
    { label: t("admin.bottlesWeek"), value: formatNumber(data.recent.bottles ?? 0) },
    { label: t("admin.bottlePicks"), value: formatNumber(data.bottle_interactions.picks ?? 0) },
  ];
});

const runtime = computed<DefinitionItem[]>(() => {
  const data = stats.data.value?.runtime;
  if (!data) return [];
  const ms = (value: number | null): string =>
    value === null ? t("app.none") : `${value.toFixed(1)} ms`;
  return [
    { label: t("admin.uptime"), value: `${formatNumber(data.uptime_seconds)} s` },
    {
      label: t("admin.memory"),
      value: `${formatNumber(Math.round(data.max_rss_bytes / 1024 / 1024))} MiB`,
    },
    { label: t("admin.loopLag"), value: ms(data.loop_lag_ms) },
    { label: t("admin.loopLagP95"), value: ms(data.loop_lag_p95_ms) },
    { label: t("admin.loopStalls"), value: formatNumber(data.loop_stalls) },
    { label: t("admin.telegramUpdates"), value: formatNumber(data.telegram_updates["300"] ?? 0) },
    { label: t("admin.apiRequests"), value: formatNumber(data.api_requests["300"] ?? 0) },
  ];
});

const updateProfile = computed<DefinitionItem[]>(() => {
  const data = stats.data.value?.runtime.telegram_update_types;
  if (!data) return [];
  return [
    {
      label: t("admin.newMessages"),
      value: formatNumber((data.UpdateNewMessage ?? 0) + (data.UpdateNewChannelMessage ?? 0)),
    },
    {
      label: t("admin.editedMessages"),
      value: formatNumber((data.UpdateEditMessage ?? 0) + (data.UpdateEditChannelMessage ?? 0)),
    },
    {
      label: t("admin.callbacks"),
      value: formatNumber(
        (data.UpdateBotCallbackQuery ?? 0) + (data.UpdateInlineBotCallbackQuery ?? 0),
      ),
    },
  ];
});

const activeGroups = computed<DefinitionItem[]>(() => {
  const groups = stats.data.value?.runtime.group_activity ?? [];
  if (!groups.length) return [{ label: t("app.none"), value: 0, muted: true }];
  return groups.map((group) => ({
    label: t("admin.chatId", { id: group.chat_id }),
    value: formatNumber(group.events),
    mono: true,
  }));
});

const featureCalls = computed<DefinitionItem[]>(() => {
  const calls = Object.entries(stats.data.value?.runtime.feature_calls ?? {});
  if (!calls.length) return [{ label: t("app.none"), value: 0, muted: true }];
  return calls
    .sort(([, left], [, right]) => right - left)
    .map(([feature, count]) => ({
      label: t(`admin.feature.${feature}`),
      value: formatNumber(count),
    }));
});

let refreshTimer: ReturnType<typeof setInterval> | undefined;

function refreshRuntime(): void {
  if (!document.hidden) stats.reload();
}

onMounted(() => {
  refreshTimer = setInterval(refreshRuntime, 5_000);
  document.addEventListener("visibilitychange", refreshRuntime);
});

onBeforeUnmount(() => {
  if (refreshTimer) clearInterval(refreshTimer);
  document.removeEventListener("visibilitychange", refreshRuntime);
});

function go(name: string): void {
  void router.push({ name });
}
</script>

<template>
  <PageHeader :title="t('admin.title')" />

  <StateBlock
    :loading="stats.loading.value && !stats.data.value"
    :error="stats.error.value"
    @retry="stats.reload"
  >
    <SettingsSection :label="t('admin.stats')">
      <DefinitionList :items="counters" />
    </SettingsSection>

    <SettingsSection v-if="affection.length" :label="t('me.affection')">
      <DefinitionList :items="affection" />
    </SettingsSection>

    <SettingsSection v-if="activity.length" :label="t('admin.activity')">
      <DefinitionList :items="activity" />
    </SettingsSection>

    <SettingsSection v-if="runtime.length" :label="t('admin.runtime')">
      <DefinitionList :items="runtime" />
    </SettingsSection>

    <SettingsSection v-if="updateProfile.length" :label="t('admin.updateProfile')">
      <DefinitionList :items="updateProfile" />
    </SettingsSection>

    <SettingsSection :label="t('admin.activeGroups')">
      <DefinitionList :items="activeGroups" />
    </SettingsSection>

    <SettingsSection :label="t('admin.featureCalls')">
      <DefinitionList :items="featureCalls" />
    </SettingsSection>

    <SettingsSection>
      <SettingsRow
        :label="t('admin.config')"
        :hint="t('admin.configHint')"
        navigable
        @click="go('admin-config')"
      />
      <SettingsRow :label="t('admin.chatList')" navigable @click="go('admin-chats')" />
      <SettingsRow :label="t('admin.userList')" navigable @click="go('admin-users')" />
      <SettingsRow
        :label="t('chatPolicy.title')"
        :hint="t('chatPolicy.subtitle')"
        navigable
        @click="go('admin-chat-policies')"
      />
      <SettingsRow :label="t('admin.jobs')" navigable @click="go('admin-jobs')" />
    </SettingsSection>

    <SettingsSection v-if="session.isOwner">
      <SettingsRow :label="t('admin.isOwner')" :value="t('app.yes')" />
    </SettingsSection>
  </StateBlock>
</template>
