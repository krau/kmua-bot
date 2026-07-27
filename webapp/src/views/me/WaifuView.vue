<script setup lang="ts">
/**
 * Waifu status: the marriage, and who was drawn in each group.
 *
 * Divorce is the only action, and it notifies the other person, so the confirmation
 * says so explicitly rather than asking a bare "are you sure".
 */
import { computed, ref } from "vue";

import { divorce, fetchMyWaifu } from "@/api/endpoints/me";
import { isApiError } from "@/api/errors";
import DefinitionList, { type DefinitionItem } from "@/components/DefinitionList.vue";
import PageHeader from "@/components/PageHeader.vue";
import SettingsRow from "@/components/SettingsRow.vue";
import SettingsSection from "@/components/SettingsSection.vue";
import StateBlock from "@/components/StateBlock.vue";
import { useAsyncData } from "@/composables/useAsyncData";
import { useNotice } from "@/composables/useNotice";
import { t, tError } from "@/i18n";
import { useMeStore } from "@/stores/me";
import { confirm, haptics } from "@/telegram";

const meStore = useMeStore();
const { notify, notifyError } = useNotice();

const divorcing = ref(false);

const waifu = useAsyncData((signal) => fetchMyWaifu(signal));

const marriageItems = computed<DefinitionItem[]>(() => {
  const data = waifu.data.value;
  if (!data) return [];
  return [
    { label: t("me.married"), value: data.is_married ? t("app.yes") : t("app.no") },
    {
      label: t("me.marriedTo"),
      value: data.married_waifu_name ?? t("app.none"),
      muted: !data.married_waifu_name,
    },
  ];
});

const entries = computed(() => waifu.data.value?.entries ?? []);

async function onDivorce(): Promise<void> {
  const name = waifu.data.value?.married_waifu_name ?? "";
  const ok = await confirm({
    title: t("me.divorce"),
    message: t("me.divorceConfirm", { name }),
    confirmText: t("me.divorce"),
    destructive: true,
  });
  if (!ok) return;

  // Divorce notifies the other person over Telegram, so it is not instant.
  divorcing.value = true;
  try {
    waifu.data.value = await divorce();
    // The marriage flags live on the profile too; refresh so it does not go stale.
    await meStore.load(true);
    notify(t("me.divorceDone"));
    haptics.success();
  } catch (error) {
    notifyError(isApiError(error) ? tError(error.code) : t("app.loadFailed"));
    haptics.error();
  } finally {
    divorcing.value = false;
  }
}
</script>

<template>
  <PageHeader :title="t('me.waifu')" />

  <StateBlock
    :loading="waifu.loading.value && !waifu.data.value"
    :error="waifu.error.value"
    @retry="waifu.reload"
  >
    <SettingsSection>
      <DefinitionList :items="marriageItems" />
      <SettingsRow
        v-if="waifu.data.value?.is_married"
        :label="t('me.divorce')"
        :hint="divorcing ? t('app.working') : undefined"
        navigable
        destructive
        :busy="divorcing"
        @click="onDivorce"
      />
    </SettingsSection>

    <SettingsSection :label="t('me.waifuInChats')">
      <SettingsRow
        v-for="entry in entries"
        :key="entry.chat_id"
        :label="entry.chat_title"
        :value="entry.waifu_name ?? t('me.noWaifu')"
      />
      <p v-if="entries.length === 0" class="px-related py-related text-sub text-hint">
        {{ t("app.empty") }}
      </p>
    </SettingsSection>
  </StateBlock>
</template>
