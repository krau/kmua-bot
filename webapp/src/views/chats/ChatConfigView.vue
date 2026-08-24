<script setup lang="ts">
/**
 * Group configuration.
 *
 * The whole config document is submitted at once, matching the API: it is a single
 * JSON column that the inline /config keyboard also writes, and replacing it wholly
 * makes the last writer's intent unambiguous.
 *
 * Title permissions and the admin roster have their own pages, so saving the toggles
 * here can never clobber them.
 */
import { computed, ref } from "vue";
import { useRouter } from "vue-router";

import { systemInfo } from "@/api/endpoints/auth";
import { fetchChat, saveChatConfig } from "@/api/endpoints/chats";
import { isApiError } from "@/api/errors";
import type { ChatConfigInput } from "@/api/types";
import NumberField from "@/components/NumberField.vue";
import NumberStepper from "@/components/NumberStepper.vue";
import PageHeader from "@/components/PageHeader.vue";
import SelectField from "@/components/SelectField.vue";
import SettingsRow from "@/components/SettingsRow.vue";
import SettingsSection from "@/components/SettingsSection.vue";
import StateBlock from "@/components/StateBlock.vue";
import TextArea from "@/components/TextArea.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import { useAsyncData } from "@/composables/useAsyncData";
import { useDirtyState } from "@/composables/useDirtyState";
import { useMainButton } from "@/composables/useMainButton";
import { useNotice } from "@/composables/useNotice";
import { t, tOptional } from "@/i18n";
import { tError } from "@/i18n";
import { haptics } from "@/telegram";
import { localeName } from "@/utils/locale";
import { TOGGLES_WITH_HINTS, TOGGLE_GROUPS, type ChatToggleKey } from "./config-layout";

const props = defineProps<{ chatId: number }>();

const router = useRouter();
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
  sticker_memory_enabled: true,
  parse_wechat_enabled: true,
  rss_agent_summary: false,
  rss_agent_broadcast: false,
  verify_enabled: false,
  verify_strategy: "all",
  verify_method: "math_easy",
  verify_max_attempts: 3,
  verify_timeout_seconds: 120,
  verify_fail_action: "kick",
  lang: "zh-CN",
};

const form = useDirtyState<ChatConfigInput & Record<string, unknown>>({ ...EMPTY_CONFIG });

const chat = useAsyncData(async (signal) => {
  const detail = await fetchChat(props.chatId, signal);
  const {
    title_permissions: _ignored,
    verify_questions: _ignoredQuestions,
    ...config
  } = detail.config;
  form.commit({ ...config });
  return detail;
});

const locales = useAsyncData(async (signal) => (await systemInfo(signal)).available_locales);

const localeOptions = computed(() =>
  (locales.data.value ?? [form.draft.value.lang]).map((value) => ({
    value,
    text: localeName(value),
  })),
);

const strategyOptions = [
  { value: "all", text: t("verify.strategy.all") },
  { value: "first_message", text: t("verify.strategy.first_message") },
];

const methodOptions = [
  { value: "math_easy", text: t("verify.method.math_easy") },
  { value: "math_hard", text: t("verify.method.math_hard") },
  { value: "emoji", text: t("verify.method.emoji") },
  { value: "sticker", text: t("verify.method.sticker") },
  { value: "custom_qa", text: t("verify.method.custom_qa") },
];

const failActionOptions = [
  { value: "kick", text: t("verify.failAction.kick") },
  { value: "ban", text: t("verify.failAction.ban") },
  { value: "unrestrict", text: t("verify.failAction.unrestrict") },
];

/** The greeting is nullable in the API but a textarea needs a string. */
const greeting = computed({
  get: () => form.draft.value.greeting ?? "",
  set: (value: string) => {
    form.draft.value.greeting = value.trim() ? value : null;
  },
});

function toggleLabel(key: ChatToggleKey): string {
  return t(`chatConfig.${key}`);
}

function toggleHint(key: ChatToggleKey): string | undefined {
  return TOGGLES_WITH_HINTS.has(key) ? tOptional(`chatConfig.${key}Hint`) : undefined;
}

function changed(key: string): boolean {
  return form.changedFields.value.includes(key);
}

async function save(): Promise<void> {
  saving.value = true;
  try {
    const saved = await saveChatConfig(props.chatId, form.draft.value);
    const { title_permissions: _ignored, verify_questions: _ignoredQuestions, ...config } = saved;
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

function go(name: string): void {
  void router.push({ name, params: { chatId: String(props.chatId) } });
}
</script>

<template>
  <PageHeader :title="t('chats.config')" :subtitle="chat.data.value?.title" />

  <StateBlock
    :loading="chat.loading.value && !chat.data.value"
    :error="chat.error.value"
    @retry="chat.reload"
  >
    <SettingsSection
      v-for="group in TOGGLE_GROUPS"
      :key="group.labelKey"
      :label="t(`chats.${group.labelKey}`)"
    >
      <SettingsRow
        v-for="key in group.keys"
        :key="key"
        :label="toggleLabel(key)"
        :hint="toggleHint(key)"
        :changed="changed(key)"
      >
        <template #control>
          <ToggleSwitch v-model="form.draft.value[key] as boolean" :aria-label="toggleLabel(key)" />
        </template>
      </SettingsRow>

      <NumberStepper
        v-if="group.labelKey === 'interaction'"
        v-model="form.draft.value.quote_probability"
        :label="t('chats.quoteProbability')"
      />

      <SettingsRow
        v-if="group.labelKey === 'content'"
        :label="t('chatConfig.parseSites')"
        :hint="t('chatConfig.parseSitesHint')"
        navigable
        @click="go('chat-parse-sites')"
      />
    </SettingsSection>

    <SettingsSection :label="t('chats.greeting')">
      <TextArea
        v-model="greeting"
        :label="t('chats.greeting')"
        :hint="t('chats.greetingHint')"
        :placeholder="t('chats.greetingPlaceholder')"
        :maxlength="1024"
        :changed="changed('greeting')"
      />
      <SelectField
        v-model="form.draft.value.lang"
        :label="t('chats.lang')"
        :options="localeOptions"
        :changed="changed('lang')"
      />
    </SettingsSection>

    <SettingsSection :label="t('chats.verify')">
      <SettingsRow :label="t('chatConfig.verify_enabled')" :changed="changed('verify_enabled')">
        <template #control>
          <ToggleSwitch
            v-model="form.draft.value.verify_enabled as boolean"
            :aria-label="t('chatConfig.verify_enabled')"
          />
        </template>
      </SettingsRow>
      <SelectField
        v-model="form.draft.value.verify_strategy"
        :label="t('chatConfig.verify_strategy')"
        :options="strategyOptions"
        :changed="changed('verify_strategy')"
      />
      <SelectField
        v-model="form.draft.value.verify_method"
        :label="t('chatConfig.verify_method')"
        :options="methodOptions"
        :changed="changed('verify_method')"
      />
      <SelectField
        v-model="form.draft.value.verify_fail_action"
        :label="t('chatConfig.verify_fail_action')"
        :options="failActionOptions"
        :changed="changed('verify_fail_action')"
      />
      <NumberField
        v-model="form.draft.value.verify_max_attempts"
        :label="t('chatConfig.verify_max_attempts')"
        :min="1"
        :max="10"
        :changed="changed('verify_max_attempts')"
      />
      <NumberField
        v-model="form.draft.value.verify_timeout_seconds"
        :label="t('chatConfig.verify_timeout_seconds')"
        :min="30"
        :max="600"
        :changed="changed('verify_timeout_seconds')"
      />
      <SettingsRow
        :label="t('chats.verifyQuestions')"
        :hint="t('chats.verifyQuestionsHint')"
        navigable
        @click="go('chat-verify-questions')"
      />
    </SettingsSection>

    <SettingsSection>
      <SettingsRow
        :label="t('chats.titlePermissions')"
        :hint="t('chats.titlePermissionsHint')"
        navigable
        @click="go('chat-title-permissions')"
      />
      <SettingsRow
        :label="t('chats.admins')"
        :hint="t('chats.adminsHint')"
        navigable
        @click="go('chat-admins')"
      />
      <SettingsRow
        :label="t('chats.quotes')"
        :value="chat.data.value?.quote_count ?? 0"
        navigable
        @click="go('chat-quotes')"
      />
      <SettingsRow
        :label="t('chats.rss')"
        :hint="t('chats.rssHint')"
        navigable
        @click="go('chat-rss')"
      />
      <SettingsRow :label="t('chats.members')" :value="chat.data.value?.member_count ?? 0" />
    </SettingsSection>
  </StateBlock>
</template>
