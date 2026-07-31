<script setup lang="ts">
/**
 * Operator-controlled per-chat policy.
 *
 * These are decisions the bot's operator makes about individual chats, as opposed to
 * the group settings page, which the chat's own admins edit. The agent whitelist is the
 * first such flag: it used to live in `settings.toml`, which meant an SSH session and a
 * config reload to onboard one group. It is operational data, so it now lives in the
 * database and is edited here - a save takes effect on the next message.
 *
 * Two things this page has to be honest about:
 *
 * 1. With `agent_whitelist_mode` off the flag is inert - the agent answers everywhere.
 *    Showing a list of "allowed" chats without saying that would be actively
 *    misleading, so the mode is stated first.
 * 2. A chat can have policy set before the bot has ever seen it, in which case there is
 *    no title to show. The row falls back to the bare id rather than inventing a name.
 *
 * The rows are a directory: tapping one opens the detail view where the flags live.
 * A list row has no room to say what each of several flags means, and a second flag
 * would have made it two toggles with no labels - the detail page is where a flag
 * gets its explanation next to its switch.
 */
import { computed, ref } from "vue";
import { useRouter } from "vue-router";

import { fetchChatPolicies, setChatPolicy } from "@/api/endpoints/admin";
import { isApiError } from "@/api/errors";
import type { ChatPolicy } from "@/api/types";
import PageHeader from "@/components/PageHeader.vue";
import SettingsRow from "@/components/SettingsRow.vue";
import SettingsSection from "@/components/SettingsSection.vue";
import StateBlock from "@/components/StateBlock.vue";
import TextField from "@/components/TextField.vue";
import { useAsyncData } from "@/composables/useAsyncData";
import { useNotice } from "@/composables/useNotice";
import { t, tError } from "@/i18n";
import { useSessionStore } from "@/stores/session";
import { haptics } from "@/telegram";
import { formatDate } from "@/utils/format";

const session = useSessionStore();
const router = useRouter();
const { notify, notifyError } = useNotice();

const newChatId = ref("");
const newNote = ref("");
/** Which action is in flight: `add`. */
const pending = ref<"add" | null>(null);
const busy = computed(() => pending.value !== null);

const policies = useAsyncData((signal) => fetchChatPolicies(signal));

const items = computed(() => policies.data.value?.items ?? []);
const whitelistMode = computed(() => policies.data.value?.agent_whitelist_mode ?? false);
const rssWhitelistMode = computed(() => policies.data.value?.rss_whitelist_mode ?? false);

/**
 * A group id is negative and Telegram supergroup ids are long, so the field is
 * validated rather than typed as a number: `-1001234567890` in a number input is
 * awkward on a phone keypad and easy to mistype into a positive id.
 */
const parsedChatId = computed(() => {
  const raw = newChatId.value.trim();
  if (!/^-?\d{1,20}$/.test(raw)) return null;
  const value = Number(raw);
  return Number.isSafeInteger(value) && value !== 0 ? value : null;
});

const isAlreadyListed = computed(
  () =>
    parsedChatId.value !== null && items.value.some((item) => item.chat_id === parsedChatId.value),
);

const canAdd = computed(() => parsedChatId.value !== null && !busy.value && !isAlreadyListed.value);

function label(item: ChatPolicy): string {
  return item.chat_title ?? String(item.chat_id);
}

/** The id plus whatever context there is, on the row's second line. */
function hint(item: ChatPolicy): string {
  const parts = [String(item.chat_id)];
  if (item.note) parts.push(item.note);
  parts.push(formatDate(item.created_at));
  return parts.join(" · ");
}

async function add(): Promise<void> {
  const chatId = parsedChatId.value;
  if (chatId === null || busy.value) return;

  pending.value = "add";
  try {
    policies.data.value = await setChatPolicy(chatId, {
      agent_allowed: true,
      note: newNote.value.trim() || null,
    });
    newChatId.value = "";
    newNote.value = "";
    notify(t("chatPolicy.added"));
    haptics.success();
  } catch (error) {
    notifyError(isApiError(error) ? tError(error.code) : t("app.loadFailed"));
    haptics.error();
  } finally {
    pending.value = null;
  }
}

function open(item: ChatPolicy): void {
  if (busy.value) return;
  void router.push({ name: "admin-chat-policy", params: { chatId: String(item.chat_id) } });
}
</script>

<template>
  <PageHeader :title="t('chatPolicy.title')" :subtitle="t('chatPolicy.subtitle')" />

  <StateBlock
    :loading="policies.loading.value && !policies.data.value"
    :error="policies.error.value"
    @retry="policies.reload"
  >
    <SettingsSection>
      <SettingsRow
        :label="t('chatPolicy.agentMode')"
        :value="whitelistMode ? t('app.yes') : t('app.no')"
        :hint="whitelistMode ? t('chatPolicy.agentModeOn') : t('chatPolicy.agentModeOff')"
      />
      <SettingsRow
        :label="t('chatPolicy.rssMode')"
        :value="rssWhitelistMode ? t('app.yes') : t('app.no')"
        :hint="rssWhitelistMode ? t('chatPolicy.rssModeOn') : t('chatPolicy.rssModeOff')"
      />
    </SettingsSection>

    <SettingsSection
      :label="t('chatPolicy.chats')"
      :hint="items.length ? t('chatPolicy.chatsHint') : t('chatPolicy.emptyHint')"
    >
      <SettingsRow
        v-for="item in items"
        :key="item.chat_id"
        :label="label(item)"
        :hint="hint(item)"
        navigable
        :disabled="busy"
        @click="open(item)"
      />
      <p v-if="items.length === 0" class="px-related py-related text-sub text-hint">
        {{ t("app.empty") }}
      </p>
    </SettingsSection>

    <!-- Writes are owner-only server-side, so a global admin is not shown a form
         that would be refused. -->
    <template v-if="session.isOwner">
      <SettingsSection :label="t('chatPolicy.add')" :hint="t('chatPolicy.addHint')">
        <TextField
          v-model="newChatId"
          :label="t('chatPolicy.chatId')"
          :placeholder="t('chatPolicy.chatIdPlaceholder')"
          inputmode="text"
          :maxlength="24"
          :hint="isAlreadyListed ? t('chatPolicy.alreadyListed') : undefined"
        />
        <TextField
          v-model="newNote"
          :label="t('chatPolicy.note')"
          :placeholder="t('chatPolicy.notePlaceholder')"
          :maxlength="256"
        />
        <SettingsRow
          :label="t('chatPolicy.add')"
          navigable
          :disabled="!canAdd"
          :busy="pending === 'add'"
          @click="add"
        />
      </SettingsSection>
    </template>
  </StateBlock>
</template>
