<script setup lang="ts">
/**
 * The caller's own profile.
 *
 * The only editable fields are language and the waifu mention flag; everything else
 * is read-only because it is earned in chat, not set here. Saving goes through the
 * native main button, which stays disabled until something actually changed.
 */
import { computed, ref } from "vue";
import { useRouter } from "vue-router";

import { refreshMyAvatar } from "@/api/endpoints/me";
import { systemInfo } from "@/api/endpoints/auth";
import { isApiError } from "@/api/errors";
import DefinitionList, { type DefinitionItem } from "@/components/DefinitionList.vue";
import PageHeader from "@/components/PageHeader.vue";
import SelectField from "@/components/SelectField.vue";
import SettingsRow from "@/components/SettingsRow.vue";
import SettingsSection from "@/components/SettingsSection.vue";
import StateBlock from "@/components/StateBlock.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import { useAsyncData } from "@/composables/useAsyncData";
import { useDirtyState } from "@/composables/useDirtyState";
import { useMainButton } from "@/composables/useMainButton";
import { useNotice } from "@/composables/useNotice";
import { t, tError } from "@/i18n";
import { useMeStore } from "@/stores/me";
import { haptics } from "@/telegram";
import { formatNumber, formatPercent } from "@/utils/format";
import { localeName } from "@/utils/locale";

const router = useRouter();
const meStore = useMeStore();

const saving = ref(false);
const { notify, notifyError } = useNotice();

const profile = useAsyncData(async () => {
  const me = await meStore.load(true);
  form.commit({ lang: me.lang, waifu_mention: me.waifu_mention });
  return me;
});

const form = useDirtyState({ lang: "zh-CN", waifu_mention: false });

// The bot may ship locales the panel has no catalogue for; offer what the bot
// accepts and let the i18n layer fall back for the ones it does not know.
const locales = useAsyncData(async (signal) => (await systemInfo(signal)).available_locales);

const localeOptions = computed(() =>
  (locales.data.value ?? [form.draft.value.lang]).map((value) => ({
    value,
    text: localeName(value),
  })),
);

const accountItems = computed<DefinitionItem[]>(() => {
  const me = profile.data.value;
  if (!me) return [];
  return [
    { label: t("me.id"), value: me.id, mono: true },
    { label: t("me.username"), value: me.username ? `@${me.username}` : t("app.none") },
  ];
});

const economyItems = computed<DefinitionItem[]>(() => {
  const me = profile.data.value;
  if (!me) return [];
  const items: DefinitionItem[] = [
    { label: t("me.coins"), value: formatNumber(me.coins) },
    { label: t("me.affection"), value: formatNumber(me.affection) },
  ];
  if (me.affection_percentile !== null) {
    items.push({ label: t("me.percentile"), value: formatPercent(me.affection_percentile) });
  }
  return items;
});

async function save(): Promise<void> {
  saving.value = true;
  try {
    const updated = await meStore.save({
      lang: form.draft.value.lang,
      waifu_mention: form.draft.value.waifu_mention,
    });
    profile.data.value = updated;
    form.commit({ lang: updated.lang, waifu_mention: updated.waifu_mention });
    notify(t("app.saved"));
    haptics.success();
  } catch (error) {
    notifyError(isApiError(error) ? tError(error.code) : t("app.loadFailed"));
    haptics.error();
  } finally {
    saving.value = false;
  }
}

useMainButton({
  text: () => t("app.saveCount", { count: form.changedFields.value.length }),
  visible: () => form.isDirty.value,
  enabled: () => form.isDirty.value && !saving.value,
  loading: () => saving.value,
  onClick: () => void save(),
  secondary: {
    text: () => t("app.reset"),
    visible: () => form.isDirty.value,
    onClick: () => form.reset(),
  },
});

/**
 * Re-downloading the avatar from Telegram takes a few seconds, so the row reports that
 * it is working. Without it the tap looked like it did nothing until the notice landed.
 */
const refreshingAvatar = ref(false);

async function onRefreshAvatar(): Promise<void> {
  refreshingAvatar.value = true;
  try {
    const result = await refreshMyAvatar();
    notify(result.refreshed ? t("me.avatarRefreshed") : t("me.avatarUnchanged"));
    haptics.success();
  } catch (error) {
    notifyError(isApiError(error) ? tError(error.code) : t("app.loadFailed"));
    haptics.error();
  } finally {
    refreshingAvatar.value = false;
  }
}
</script>

<template>
  <PageHeader :title="t('me.title')" :subtitle="profile.data.value?.full_name" />

  <StateBlock
    :loading="profile.loading.value && !profile.data.value"
    :error="profile.error.value"
    @retry="profile.reload"
  >
    <SettingsSection :label="t('me.profile')">
      <DefinitionList :items="accountItems" />
      <SelectField
        v-model="form.draft.value.lang"
        :label="t('me.lang')"
        :options="localeOptions"
        :changed="form.changedFields.value.includes('lang')"
      />
    </SettingsSection>

    <SettingsSection :label="t('me.economy')">
      <DefinitionList :items="economyItems" />
    </SettingsSection>

    <SettingsSection :label="t('me.waifu')">
      <SettingsRow
        :label="t('me.waifuMention')"
        :changed="form.changedFields.value.includes('waifu_mention')"
      >
        <template #control>
          <ToggleSwitch
            v-model="form.draft.value.waifu_mention"
            :aria-label="t('me.waifuMention')"
          />
        </template>
      </SettingsRow>
      <SettingsRow
        :label="t('me.waifuInChats')"
        :value="profile.data.value?.is_married ? profile.data.value.married_waifu_name : undefined"
        navigable
        @click="router.push({ name: 'me-waifu' })"
      />
    </SettingsSection>

    <SettingsSection :label="t('me.content')">
      <SettingsRow
        :label="t('me.quotes')"
        :value="profile.data.value?.quote_count ?? 0"
        navigable
        @click="router.push({ name: 'me-quotes' })"
      />
      <SettingsRow
        :label="t('me.gifts')"
        :value="profile.data.value?.gift_count ?? 0"
        navigable
        @click="router.push({ name: 'me-gifts' })"
      />
      <SettingsRow
        :label="t('me.chats')"
        :value="profile.data.value?.chat_count ?? 0"
        navigable
        @click="router.push({ name: 'chats' })"
      />
      <SettingsRow
        :label="t('me.rss')"
        :hint="t('me.rssHint')"
        navigable
        @click="router.push({ name: 'me-rss' })"
      />
    </SettingsSection>

    <SettingsSection :label="t('me.avatar')">
      <SettingsRow
        :label="t('me.refreshAvatar')"
        :hint="refreshingAvatar ? t('app.working') : undefined"
        navigable
        :busy="refreshingAvatar"
        @click="onRefreshAvatar"
      />
    </SettingsSection>
  </StateBlock>
</template>
