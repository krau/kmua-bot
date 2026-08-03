<script setup lang="ts">
/**
 * Per-site link-parsing switches.
 *
 * The whole config document is submitted at once, matching the API: it is a
 * single JSON column, so the page loads the full config and only edits the
 * parse_sites_enabled subset before saving.
 */
import { ref } from "vue";

import { fetchChat, saveChatConfig } from "@/api/endpoints/chats";
import { isApiError } from "@/api/errors";
import type { ChatConfigInput } from "@/api/types";
import PageHeader from "@/components/PageHeader.vue";
import SettingsRow from "@/components/SettingsRow.vue";
import SettingsSection from "@/components/SettingsSection.vue";
import StateBlock from "@/components/StateBlock.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import { useAsyncData } from "@/composables/useAsyncData";
import { useDirtyState } from "@/composables/useDirtyState";
import { useMainButton } from "@/composables/useMainButton";
import { useNotice } from "@/composables/useNotice";
import { t } from "@/i18n";
import { tError } from "@/i18n";
import { haptics } from "@/telegram";

const props = defineProps<{ chatId: number }>();

const saving = ref(false);
const { notify, notifyError } = useNotice();

const EMPTY_CONFIG: ChatConfigInput = {
  waifu_enabled: true,
  delete_events_enabled: false,
  unpin_channel_pin_enabled: false,
  quote_probability: 0.001,
  quote_pin_message: true,
  greeting: null,
  ai_reply: true,
  ai_reply_other_bots_enabled: false,
  ai_comment: false,
  setu_enabled: true,
  convert_b23_enabled: true,
  parse_links_enabled: true,
  parse_artwork_enabled: true,
  parse_sites_enabled: {},
  pick_bottle_enabled: true,
  group_memory_enabled: true,
  parse_wechat_enabled: true,
  rss_agent_summary: false,
  rss_agent_broadcast: false,
  lang: "zh-CN",
};

const form = useDirtyState<ChatConfigInput & Record<string, unknown>>({ ...EMPTY_CONFIG });

const chat = useAsyncData(async (signal) => {
  const detail = await fetchChat(props.chatId, signal);
  const { title_permissions: _ignored, ...config } = detail.config;
  form.commit({ ...config });
  return detail;
});

/** Per-site link parsers; keys must match the backend parse_sites_enabled keys. */
const PARSE_SITES = [
  { key: "wechat", label: "微信公众号" },
  { key: "coolapk", label: "酷安" },
  { key: "tieba", label: "贴吧" },
  { key: "pixiv", label: "Pixiv" },
  { key: "bilibili", label: "Bilibili" },
  { key: "danbooru", label: "Danbooru" },
  { key: "kemono", label: "Kemono" },
  { key: "yandere", label: "Yande.re" },
  { key: "nhentai", label: "Nhentai" },
  { key: "twitter", label: "Twitter/X" },
] as const;

function siteEnabled(key: string): boolean {
  return form.draft.value.parse_sites_enabled?.[key] ?? true;
}

function setSiteEnabled(key: string, value: boolean): void {
  form.draft.value.parse_sites_enabled[key] = value;
}

async function save(): Promise<void> {
  saving.value = true;
  try {
    const saved = await saveChatConfig(props.chatId, form.draft.value);
    const { title_permissions: _ignored, ...config } = saved;
    form.commit({ ...config });
    if (chat.data.value) chat.data.value.config = saved;
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
</script>

<template>
  <PageHeader :title="t('chatConfig.parseSites')" :subtitle="chat.data.value?.title" />

  <StateBlock
    :loading="chat.loading.value && !chat.data.value"
    :error="chat.error.value"
    @retry="chat.reload"
  >
    <SettingsSection :hint="t('chatConfig.parseSitesHint')">
      <SettingsRow v-for="site in PARSE_SITES" :key="site.key" :label="site.label">
        <template #control>
          <ToggleSwitch
            :model-value="siteEnabled(site.key)"
            :aria-label="site.label"
            @update:model-value="(v: boolean) => setSiteEnabled(site.key, v)"
          />
        </template>
      </SettingsRow>
    </SettingsSection>
  </StateBlock>
</template>
