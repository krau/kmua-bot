<script setup lang="ts">
/**
 * Developer panel home: the counters, plus links to the rest.
 *
 * The counters are shown as an aligned definition list, not as five big numbers in
 * separate cards. They are real measurements of unrelated things, and a stat-card row
 * would give them equal visual weight while implying they belong together.
 */
import { computed } from "vue";
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
