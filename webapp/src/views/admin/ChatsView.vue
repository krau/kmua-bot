<script setup lang="ts">
/**
 * All groups the bot knows about, searchable.
 */
import { computed, ref, watch } from "vue";
import { useRouter } from "vue-router";

import { fetchChats } from "@/api/endpoints/admin";
import PageHeader from "@/components/PageHeader.vue";
import PagerBar from "@/components/PagerBar.vue";
import SettingsRow from "@/components/SettingsRow.vue";
import SettingsSection from "@/components/SettingsSection.vue";
import StateBlock from "@/components/StateBlock.vue";
import TextField from "@/components/TextField.vue";
import { useAsyncData } from "@/composables/useAsyncData";
import { useDebouncedRef } from "@/composables/useDebouncedRef";
import { t } from "@/i18n";

const PAGE_SIZE = 20;

const router = useRouter();
const page = ref(1);
const search = ref("");
const debouncedSearch = useDebouncedRef(search, 300);

const chats = useAsyncData((signal) =>
  fetchChats(page.value, PAGE_SIZE, debouncedSearch.value, signal),
);

watch(page, () => void chats.reload());
watch(debouncedSearch, () => {
  if (page.value !== 1) {
    page.value = 1;
    return;
  }
  void chats.reload();
});

const items = computed(() => chats.data.value?.items ?? []);
const total = computed(() => chats.data.value?.total ?? 0);
</script>

<template>
  <PageHeader :title="t('admin.chatList')" :subtitle="String(total)" />

  <SettingsSection>
    <TextField
      v-model="search"
      :label="t('app.search')"
      :placeholder="t('admin.searchChats')"
      inputmode="search"
      :maxlength="128"
    />
  </SettingsSection>

  <StateBlock
    :loading="chats.loading.value && !chats.data.value"
    :error="chats.error.value"
    :empty="!chats.loading.value && items.length === 0"
    @retry="chats.reload"
  >
    <SettingsSection>
      <SettingsRow
        v-for="chat in items"
        :key="chat.id"
        :label="chat.title"
        :hint="chat.username ? `@${chat.username}` : String(chat.id)"
        :value="chat.member_count"
        navigable
        @click="router.push({ name: 'admin-chat', params: { chatId: String(chat.id) } })"
      />
    </SettingsSection>

    <PagerBar v-model:page="page" :size="PAGE_SIZE" :total="total" :loading="chats.loading.value" />
  </StateBlock>
</template>
