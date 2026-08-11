<script setup lang="ts">
/**
 * A group as the developer panel sees it: read-only config plus the leave action.
 *
 * The config is shown but not editable here - editing lives on the chat admin page,
 * which is the same surface a group admin uses. Duplicating the editor would mean two
 * code paths writing the same column.
 *
 * Leaving is owner-only and cascades: quotes, waifu pairings and member records go
 * with it. The confirmation says exactly that.
 */
import { computed, ref } from "vue";
import { useRouter } from "vue-router";

import { blockChat, fetchChat, leaveChat, unblockChat } from "@/api/endpoints/admin";
import { isApiError } from "@/api/errors";
import DefinitionList, { type DefinitionItem } from "@/components/DefinitionList.vue";
import PageHeader from "@/components/PageHeader.vue";
import SettingsRow from "@/components/SettingsRow.vue";
import SettingsSection from "@/components/SettingsSection.vue";
import StateBlock from "@/components/StateBlock.vue";
import { useAsyncData } from "@/composables/useAsyncData";
import { useNotice } from "@/composables/useNotice";
import { t, tError } from "@/i18n";
import { useSessionStore } from "@/stores/session";
import { confirm, haptics } from "@/telegram";
import { formatDateTime, formatPercent } from "@/utils/format";

const props = defineProps<{ chatId: number }>();

const router = useRouter();
const session = useSessionStore();

const leaving = ref(false);
const blocking = ref(false);
const { notify, notifyError } = useNotice();

const chat = useAsyncData((signal) => fetchChat(props.chatId, signal));

const overview = computed<DefinitionItem[]>(() => {
  const data = chat.data.value;
  if (!data) return [];
  return [
    { label: t("me.id"), value: data.id, mono: true },
    { label: t("me.username"), value: data.username ? `@${data.username}` : t("app.none") },
    { label: t("chats.members"), value: data.member_count },
    { label: t("chats.quotes"), value: data.quote_count },
    { label: t("admin.created"), value: formatDateTime(data.created_at) },
  ];
});

const configItems = computed<DefinitionItem[]>(() => {
  const config = chat.data.value?.config;
  if (!config) return [];
  const items: DefinitionItem[] = Object.entries(config)
    .filter(([, value]) => typeof value === "boolean")
    .map(([key, value]) => ({
      label: key,
      value: value ? t("app.yes") : t("app.no"),
      mono: true,
    }));
  items.push({
    label: "quote_probability",
    value: formatPercent(config.quote_probability, 3),
    mono: true,
  });
  items.push({ label: "lang", value: config.lang, mono: true });
  return items;
});

async function onToggleBlock(): Promise<void> {
  const title = chat.data.value?.title ?? String(props.chatId);
  const blocked = chat.data.value?.is_blocked ?? false;
  const ok = await confirm({
    title: t(blocked ? "admin.unblockChat" : "admin.blockChat"),
    message: t(blocked ? "admin.unblockChatConfirm" : "admin.blockChatConfirm", { title }),
    confirmText: t(blocked ? "admin.unblockChat" : "admin.blockChat"),
    destructive: !blocked,
  });
  if (!ok) return;

  blocking.value = true;
  try {
    if (blocked) {
      await unblockChat(props.chatId);
    } else {
      await blockChat(props.chatId);
    }
    haptics.success();
    notify(t(blocked ? "admin.unblockChatDone" : "admin.blockChatDone"));
    chat.reload();
  } catch (error) {
    notifyError(isApiError(error) ? tError(error.code) : t("app.loadFailed"));
    haptics.error();
  } finally {
    blocking.value = false;
  }
}

async function onLeave(): Promise<void> {
  const title = chat.data.value?.title ?? String(props.chatId);
  const ok = await confirm({
    title: t("admin.leave"),
    message: t("admin.leaveConfirm", { title }),
    confirmText: t("admin.leave"),
    destructive: true,
  });
  if (!ok) return;

  leaving.value = true;
  try {
    await leaveChat(props.chatId);
    haptics.success();
    // The record is gone, so this page has nothing left to show.
    void router.replace({ name: "admin-chats" });
  } catch (error) {
    notifyError(isApiError(error) ? tError(error.code) : t("app.loadFailed"));
    haptics.error();
  } finally {
    leaving.value = false;
  }
}
</script>

<template>
  <PageHeader :title="chat.data.value?.title ?? t('admin.chats')" />

  <StateBlock
    :loading="chat.loading.value && !chat.data.value"
    :error="chat.error.value"
    @retry="chat.reload"
  >
    <SettingsSection>
      <DefinitionList :items="overview" />
    </SettingsSection>

    <SettingsSection>
      <SettingsRow
        :label="t('chats.config')"
        navigable
        @click="router.push({ name: 'chat-config', params: { chatId: String(chatId) } })"
      />
    </SettingsSection>

    <SettingsSection :label="t('admin.config')">
      <DefinitionList :items="configItems" />
    </SettingsSection>

    <SettingsSection v-if="session.isOwner">
      <SettingsRow
        :label="t(chat.data.value?.is_blocked ? 'admin.unblockChat' : 'admin.blockChat')"
        :hint="blocking ? t('app.working') : undefined"
        navigable
        :destructive="!chat.data.value?.is_blocked"
        :busy="blocking"
        @click="onToggleBlock"
      />
      <SettingsRow
        :label="t('admin.leave')"
        :hint="leaving ? t('app.working') : undefined"
        navigable
        destructive
        :busy="leaving"
        @click="onLeave"
      />
    </SettingsSection>
  </StateBlock>
</template>
