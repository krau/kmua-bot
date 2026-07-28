<script setup lang="ts">
/**
 * The caller's own quotes, paged.
 *
 * Deleting asks for confirmation through Telegram's native dialog: it is
 * irreversible and a stray tap on a list row should not destroy content.
 */
import { computed, ref, watch } from "vue";

import { deleteMyQuote, fetchMyQuotes } from "@/api/endpoints/me";
import { isApiError } from "@/api/errors";
import type { Quote } from "@/api/types";
import PageHeader from "@/components/PageHeader.vue";
import PagerBar from "@/components/PagerBar.vue";
import SettingsRow from "@/components/SettingsRow.vue";
import SettingsSection from "@/components/SettingsSection.vue";
import StateBlock from "@/components/StateBlock.vue";
import { useAsyncData } from "@/composables/useAsyncData";
import { useNotice } from "@/composables/useNotice";
import { t, tError } from "@/i18n";
import { confirm, haptics } from "@/telegram";
import { formatDate, truncate } from "@/utils/format";

const PAGE_SIZE = 20;

const page = ref(1);
const { notify, notifyError } = useNotice();

const quotes = useAsyncData((signal) => fetchMyQuotes(page.value, PAGE_SIZE, signal));

watch(page, () => void quotes.reload());

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
    await deleteMyQuote(quote.link);
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
  <PageHeader :title="t('quotes.title')" />

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
        :hint="`${quote.chat_title ?? quote.chat_id} · ${formatDate(quote.created_at)}`"
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
