<script setup lang="ts">
/**
 * A group's quotes, searchable and deletable.
 *
 * Search resets to page one, since results from a previous query's page 3 would be
 * meaningless. The query is debounced so typing does not fire a request per
 * keystroke.
 */
import { computed, ref, watch } from "vue";

import { deleteChatQuote, fetchChat, fetchChatQuotes } from "@/api/endpoints/chats";
import { isApiError } from "@/api/errors";
import type { Quote } from "@/api/types";
import PageHeader from "@/components/PageHeader.vue";
import PagerBar from "@/components/PagerBar.vue";
import SettingsRow from "@/components/SettingsRow.vue";
import SettingsSection from "@/components/SettingsSection.vue";
import StateBlock from "@/components/StateBlock.vue";
import TextField from "@/components/TextField.vue";
import { useAsyncData } from "@/composables/useAsyncData";
import { useDebouncedRef } from "@/composables/useDebouncedRef";
import { useNotice } from "@/composables/useNotice";
import { t, tError } from "@/i18n";
import { confirm, haptics } from "@/telegram";
import { formatDate, truncate } from "@/utils/format";

const props = defineProps<{ chatId: number }>();

const PAGE_SIZE = 20;

const page = ref(1);
const search = ref("");
const debouncedSearch = useDebouncedRef(search, 300);
const { notify, notifyError } = useNotice();

const chat = useAsyncData((signal) => fetchChat(props.chatId, signal));
const quotes = useAsyncData((signal) =>
  fetchChatQuotes(props.chatId, page.value, PAGE_SIZE, debouncedSearch.value, signal),
);

watch(page, () => void quotes.reload());
watch(debouncedSearch, () => {
  // A new query invalidates the current offset.
  if (page.value !== 1) {
    page.value = 1;
    return;
  }
  void quotes.reload();
});

const items = computed(() => quotes.data.value?.items ?? []);
const total = computed(() => quotes.data.value?.total ?? 0);

function preview(quote: Quote): string {
  if (quote.text) return truncate(quote.text);
  return quote.has_image ? t("quotes.withImage") : `#${quote.message_id}`;
}

/** Which quote is being deleted, so the spinner lands on the row that was tapped. */
const deleting = ref<string | null>(null);

async function remove(quote: Quote): Promise<void> {
  const ok = await confirm({
    title: t("quotes.title"),
    message: t("quotes.deleteConfirm"),
    confirmText: t("app.delete"),
    destructive: true,
  });
  if (!ok) return;

  deleting.value = quote.link;
  try {
    await deleteChatQuote(props.chatId, quote.link);
    notify(t("quotes.deleted"));
    haptics.success();
    await quotes.reload();
  } catch (error) {
    notifyError(isApiError(error) ? tError(error.code) : t("app.loadFailed"));
    haptics.error();
  } finally {
    deleting.value = null;
  }
}
</script>

<template>
  <PageHeader :title="t('chats.quotes')" :subtitle="chat.data.value?.title" />

  <SettingsSection>
    <TextField
      v-model="search"
      :label="t('app.search')"
      :placeholder="t('quotes.searchPlaceholder')"
      inputmode="search"
      :maxlength="128"
    />
  </SettingsSection>

  <StateBlock
    :loading="quotes.loading.value && !quotes.data.value"
    :error="quotes.error.value"
    :empty="!quotes.loading.value && items.length === 0"
    @retry="quotes.reload"
  >
    <SettingsSection>
      <SettingsRow
        v-for="quote in items"
        :key="quote.link"
        :label="preview(quote)"
        :hint="`${quote.user_name ?? quote.user_id} · ${formatDate(quote.created_at)}`"
        :value="t('app.delete')"
        navigable
        destructive
        :disabled="deleting !== null"
        :busy="deleting === quote.link"
        @click="remove(quote)"
      />
    </SettingsSection>

    <PagerBar
      v-model:page="page"
      :size="PAGE_SIZE"
      :total="total"
      :loading="quotes.loading.value"
    />
  </StateBlock>
</template>
