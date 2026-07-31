<script setup lang="ts">
/**
 * A group's RSS/Atom subscriptions: add a feed by URL, toggle push per feed, and
 * remove. Mirrors the `/rss` command; the server enforces the same whitelist gate
 * (`rss_allowed` policy flag) on every request this page makes.
 */
import { computed, ref, watch } from "vue";

import {
  addChatRss,
  deleteChatRss,
  fetchChat,
  fetchChatRss,
  setChatRssPaused,
} from "@/api/endpoints/chats";
import { isApiError } from "@/api/errors";
import type { RssSubscription } from "@/api/types";
import PageHeader from "@/components/PageHeader.vue";
import PagerBar from "@/components/PagerBar.vue";
import SettingsRow from "@/components/SettingsRow.vue";
import SettingsSection from "@/components/SettingsSection.vue";
import StateBlock from "@/components/StateBlock.vue";
import TextField from "@/components/TextField.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import { useAsyncData } from "@/composables/useAsyncData";
import { useNotice } from "@/composables/useNotice";
import { t, tError } from "@/i18n";
import { confirm, haptics } from "@/telegram";
import { formatDate } from "@/utils/format";

const props = defineProps<{ chatId: number }>();

const PAGE_SIZE = 20;

const page = ref(1);
const newUrl = ref("");
const { notify, notifyError } = useNotice();

const chat = useAsyncData((signal) => fetchChat(props.chatId, signal));
const subscriptions = useAsyncData((signal) =>
  fetchChatRss(props.chatId, page.value, PAGE_SIZE, signal),
);

watch(page, () => void subscriptions.reload());

const items = computed(() => subscriptions.data.value?.items ?? []);
const total = computed(() => subscriptions.data.value?.total ?? 0);

/** Which action is in flight: `add`, `toggle:<feedId>` or `remove:<feedId>`. */
const pending = ref<"add" | `toggle:${number}` | `remove:${number}` | null>(null);
const busy = computed(() => pending.value !== null);

/** URL field: http(s) with no whitespace, matching the server-side check. */
const canAdd = computed(() => {
  if (busy.value) return false;
  const raw = newUrl.value.trim();
  return /^https?:\/\/\S+$/.test(raw) && raw.length <= 1024;
});

function hint(item: RssSubscription): string {
  const parts = [
    item.last_fetched_at
      ? `${t("chats.rssLastFetched")}: ${formatDate(item.last_fetched_at)}`
      : t("chats.rssNeverFetched"),
  ];
  parts.push(
    item.interval_minutes
      ? t("chats.rssEvery", { minutes: item.interval_minutes })
      : t("chats.rssGlobalInterval"),
  );
  if (item.last_error) parts.push(t("chats.rssError"));
  if (item.paused) parts.push(t("chats.rssPaused"));
  return parts.join(" · ");
}

function reportError(error: unknown): void {
  notifyError(isApiError(error) ? tError(error.code) : t("app.loadFailed"));
}

async function add(): Promise<void> {
  const url = newUrl.value.trim();
  if (!canAdd.value) return;

  pending.value = "add";
  try {
    await addChatRss(props.chatId, url);
    newUrl.value = "";
    notify(t("chats.rssAdded"));
    haptics.success();
    await subscriptions.reload();
  } catch (error) {
    reportError(error);
    haptics.error();
  } finally {
    pending.value = null;
  }
}

/** Pause/resume one feed. The row stays listed either way. */
async function toggle(item: RssSubscription, paused: boolean): Promise<void> {
  if (busy.value) return;

  pending.value = `toggle:${item.feed_id}`;
  try {
    await setChatRssPaused(props.chatId, item.feed_id, paused);
    notify(t("app.saved"));
    haptics.success();
    await subscriptions.reload();
  } catch (error) {
    reportError(error);
    haptics.error();
  } finally {
    pending.value = null;
  }
}

async function remove(item: RssSubscription): Promise<void> {
  const ok = await confirm({
    title: t("chats.rssRemove"),
    message: t("chats.rssRemoveConfirm", { name: item.title ?? item.url }),
    confirmText: t("chats.rssRemove"),
    destructive: true,
  });
  if (!ok) return;

  pending.value = `remove:${item.feed_id}`;
  try {
    await deleteChatRss(props.chatId, item.feed_id);
    notify(t("chats.rssRemoved"));
    haptics.success();
    await subscriptions.reload();
  } catch (error) {
    reportError(error);
    haptics.error();
  } finally {
    pending.value = null;
  }
}
</script>

<template>
  <PageHeader :title="t('chats.rss')" :subtitle="chat.data.value?.title" />

  <SettingsSection :label="t('chats.rssAdd')" :hint="t('chats.rssHint')">
    <TextField
      v-model="newUrl"
      :label="t('chats.rssUrl')"
      :placeholder="t('chats.rssUrlPlaceholder')"
      inputmode="url"
      :maxlength="1024"
    />
    <SettingsRow
      :label="t('chats.rssAdd')"
      navigable
      :disabled="!canAdd"
      :busy="pending === 'add'"
      @click="add"
    />
  </SettingsSection>

  <StateBlock
    :loading="subscriptions.loading.value && !subscriptions.data.value"
    :error="subscriptions.error.value"
    :empty="!subscriptions.loading.value && items.length === 0"
    @retry="subscriptions.reload"
  >
    <SettingsSection
      :label="t('chats.rss')"
      :hint="items.length ? t('chats.rssActive') : t('chats.rssEmpty')"
    >
      <SettingsRow
        v-for="item in items"
        :key="item.feed_id"
        :label="item.title ?? item.url"
        :hint="hint(item)"
        :disabled="busy"
      >
        <template #control>
          <ToggleSwitch
            :model-value="!item.paused"
            :disabled="busy"
            :busy="pending === `toggle:${item.feed_id}`"
            :aria-label="item.paused ? t('chats.rssPaused') : t('chats.rssActive')"
            @update:model-value="toggle(item, !$event)"
          />
        </template>
      </SettingsRow>
    </SettingsSection>

    <PagerBar
      v-model:page="page"
      :size="PAGE_SIZE"
      :total="total"
      :loading="subscriptions.loading.value"
    />

    <SettingsSection v-if="items.length" :hint="t('chats.rssRemove')">
      <SettingsRow
        v-for="item in items"
        :key="item.feed_id"
        :label="item.title ?? item.url"
        :value="t('chats.rssRemove')"
        navigable
        destructive
        :disabled="busy"
        :busy="pending === `remove:${item.feed_id}`"
        @click="remove(item)"
      />
    </SettingsSection>
  </StateBlock>
</template>
