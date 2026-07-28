<script setup lang="ts">
/**
 * Bot admins for a group, plus member sync.
 *
 * Promotion is by user id, because that is what the bot itself accepts and what a
 * group admin can copy from /id. Demotion asks for confirmation and respects the
 * upstream rule the API enforces: you cannot demote whoever promoted you.
 */
import { computed, ref } from "vue";

import {
  demoteChatAdmin,
  fetchChat,
  fetchChatAdmins,
  promoteChatAdmin,
  syncChatMembers,
} from "@/api/endpoints/chats";
import { isApiError } from "@/api/errors";
import type { ChatAdmin } from "@/api/types";
import PageHeader from "@/components/PageHeader.vue";
import SettingsRow from "@/components/SettingsRow.vue";
import SettingsSection from "@/components/SettingsSection.vue";
import StateBlock from "@/components/StateBlock.vue";
import TextField from "@/components/TextField.vue";
import { useAsyncData } from "@/composables/useAsyncData";
import { useNotice } from "@/composables/useNotice";
import { t, tError } from "@/i18n";
import { confirm, haptics } from "@/telegram";

const props = defineProps<{ chatId: number }>();

const newAdminId = ref("");
/**
 * Which action is in flight, not just whether one is.
 *
 * A single boolean would disable every row but show progress on none of them, so a
 * member sync - which walks the whole roster and takes seconds - looked identical to
 * an idle page. The demote case carries the user id so the spinner lands on the row
 * that was actually tapped.
 */
const pending = ref<"add" | "sync" | `demote:${number}` | null>(null);
const busy = computed(() => pending.value !== null);
const { notify, notifyError } = useNotice();

const chat = useAsyncData((signal) => fetchChat(props.chatId, signal));
const admins = useAsyncData((signal) => fetchChatAdmins(props.chatId, signal));

const items = computed(() => admins.data.value ?? []);
const canAdd = computed(() => /^\d+$/.test(newAdminId.value.trim()) && !busy.value);

function report(error: unknown): void {
  notifyError(isApiError(error) ? tError(error.code) : t("app.loadFailed"));
  haptics.error();
}

async function add(): Promise<void> {
  if (!canAdd.value) return;
  pending.value = "add";
  try {
    admins.data.value = await promoteChatAdmin(props.chatId, Number(newAdminId.value.trim()));
    newAdminId.value = "";
    haptics.success();
  } catch (error) {
    report(error);
  } finally {
    pending.value = null;
  }
}

async function remove(admin: ChatAdmin): Promise<void> {
  const ok = await confirm({
    title: t("chats.demote"),
    message: t("chats.demoteConfirm", { name: admin.full_name }),
    confirmText: t("chats.demote"),
    destructive: true,
  });
  if (!ok) return;

  pending.value = `demote:${admin.user_id}`;
  try {
    admins.data.value = await demoteChatAdmin(props.chatId, admin.user_id);
    haptics.success();
  } catch (error) {
    report(error);
  } finally {
    pending.value = null;
  }
}

async function sync(): Promise<void> {
  pending.value = "sync";
  try {
    const result = await syncChatMembers(props.chatId);
    notify(t("chats.syncMembersDone", { count: result.removed }));
    haptics.success();
    await chat.reload();
  } catch (error) {
    report(error);
  } finally {
    pending.value = null;
  }
}
</script>

<template>
  <PageHeader :title="t('chats.admins')" :subtitle="chat.data.value?.title" />

  <StateBlock
    :loading="admins.loading.value && !admins.data.value"
    :error="admins.error.value"
    @retry="admins.reload"
  >
    <SettingsSection :hint="t('chats.adminsHint')">
      <SettingsRow
        v-for="admin in items"
        :key="admin.user_id"
        :label="admin.full_name"
        :hint="
          admin.promoted_by_name
            ? t('chats.promotedBy', { name: admin.promoted_by_name })
            : String(admin.user_id)
        "
        :value="t('chats.demote')"
        navigable
        destructive
        :disabled="busy"
        :busy="pending === `demote:${admin.user_id}`"
        @click="remove(admin)"
      />
      <p v-if="items.length === 0" class="px-related py-related text-sub text-hint">
        {{ t("app.empty") }}
      </p>
    </SettingsSection>

    <SettingsSection>
      <TextField
        v-model="newAdminId"
        :label="t('chats.addAdmin')"
        :placeholder="t('chats.addAdminPlaceholder')"
        inputmode="numeric"
        :maxlength="20"
      />
      <SettingsRow
        :label="t('chats.addAdmin')"
        navigable
        :disabled="!canAdd"
        :busy="pending === 'add'"
        @click="add"
      />
    </SettingsSection>

    <SettingsSection>
      <SettingsRow
        :label="t('chats.syncMembers')"
        :hint="pending === 'sync' ? t('app.working') : t('chats.syncMembersHint')"
        :value="chat.data.value?.member_count ?? undefined"
        navigable
        :disabled="busy"
        :busy="pending === 'sync'"
        @click="sync"
      />
    </SettingsSection>
  </StateBlock>
</template>
