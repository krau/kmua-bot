<script setup lang="ts">
/**
 * Groups the caller shares with the bot.
 *
 * Non-manageable groups are listed but not tappable, rather than hidden: seeing a
 * group and the note that you cannot configure it is clearer than wondering why it
 * is missing.
 */
import { computed } from "vue";
import { useRouter } from "vue-router";

import { fetchMyChats } from "@/api/endpoints/me";
import PageHeader from "@/components/PageHeader.vue";
import SettingsRow from "@/components/SettingsRow.vue";
import SettingsSection from "@/components/SettingsSection.vue";
import StateBlock from "@/components/StateBlock.vue";
import { useAsyncData } from "@/composables/useAsyncData";
import { t } from "@/i18n";

const router = useRouter();
const chats = useAsyncData((signal) => fetchMyChats(signal));

const manageable = computed(() => (chats.data.value ?? []).filter((chat) => chat.can_manage));
const readonly = computed(() => (chats.data.value ?? []).filter((chat) => !chat.can_manage));

function open(chatId: number): void {
  void router.push({ name: "chat-config", params: { chatId: String(chatId) } });
}
</script>

<template>
  <PageHeader :title="t('chats.title')" />

  <StateBlock
    :loading="chats.loading.value && !chats.data.value"
    :error="chats.error.value"
    :empty="!chats.loading.value && (chats.data.value?.length ?? 0) === 0"
    @retry="chats.reload"
  >
    <SettingsSection v-if="manageable.length" :label="t('chats.manageable')">
      <SettingsRow
        v-for="chat in manageable"
        :key="chat.id"
        :label="chat.title"
        :hint="chat.username ? `@${chat.username}` : String(chat.id)"
        navigable
        @click="open(chat.id)"
      />
    </SettingsSection>

    <SettingsSection v-if="readonly.length" :label="t('chats.readonly')">
      <SettingsRow
        v-for="chat in readonly"
        :key="chat.id"
        :label="chat.title"
        :hint="chat.username ? `@${chat.username}` : String(chat.id)"
      />
    </SettingsSection>
  </StateBlock>
</template>
