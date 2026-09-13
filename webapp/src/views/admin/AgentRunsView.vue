<script setup lang="ts">
/**
 * Recorded agent runs, most recent first.
 *
 * Read-only on purpose: these rows describe what the bot did, and an operator who
 * could edit them would no longer be reading a record.
 *
 * The filters are committed by the native main button, not as they are typed: the
 * text box matches anywhere inside a run's output or error message, which no index
 * can serve, so a query per keystroke would scan the whole table.
 */
import { computed, ref, watch } from "vue";
import { useRouter } from "vue-router";

import { fetchAgentRuns } from "@/api/endpoints/admin";
import type { AgentRunKind, AgentRunQuery, AgentRunStatus } from "@/api/types";
import PageHeader from "@/components/PageHeader.vue";
import PagerBar from "@/components/PagerBar.vue";
import SelectField from "@/components/SelectField.vue";
import SettingsRow from "@/components/SettingsRow.vue";
import SettingsSection from "@/components/SettingsSection.vue";
import StateBlock from "@/components/StateBlock.vue";
import TextField from "@/components/TextField.vue";
import { useAsyncData } from "@/composables/useAsyncData";
import { useDirtyState } from "@/composables/useDirtyState";
import { useMainButton } from "@/composables/useMainButton";
import { t } from "@/i18n";
import { formatDateTime, formatTokens, truncate } from "@/utils/format";

const PAGE_SIZE = 20;

const KINDS: AgentRunKind[] = [
  "chat",
  "ask",
  "followup",
  "followup_relevance",
  "channel_comment",
  "rss_digest",
  "rss_broadcast",
  "sticker_description",
  "memory",
  "transcription",
  "compaction",
];

const STATUSES: AgentRunStatus[] = ["ok", "error", "timeout", "cancelled", "rejected"];

interface FilterBoxes {
  sessionId: string;
  chatId: string;
  userId: string;
  kind: string;
  status: string;
  since: string;
  until: string;
  search: string;
}

function blank(): FilterBoxes & Record<string, unknown> {
  return {
    sessionId: "",
    chatId: "",
    userId: "",
    kind: "",
    status: "",
    since: "",
    until: "",
    search: "",
  };
}

const router = useRouter();
const page = ref(1);

/** The filter boxes, edited freely and searched when the operator says so. */
const form = useDirtyState<FilterBoxes & Record<string, unknown>>(blank());

/**
 * The committed filters, typed by the API's own query shape.
 *
 * `buildUrl` writes each key verbatim and FastAPI ignores what it does not know,
 * so a stray key would silently filter nothing; typing this as the query minus the
 * paging fields makes the next such typo a compile error.
 */
const applied = ref<Omit<AgentRunQuery, "page" | "size">>({});

// Values, not keys: every key is written on every search, an unused one as
// `undefined`, so the key count would stay at eight however little is filtered.
const hasFilters = computed(() =>
  Object.values(applied.value).some((value) => value !== undefined),
);

const kindOptions = computed(() => [
  { value: "", text: t("agentRuns.filters.all") },
  ...KINDS.map((value) => ({ value, text: t(`agentRuns.kind.${value}`) })),
]);
const statusOptions = computed(() => [
  { value: "", text: t("agentRuns.filters.all") },
  ...STATUSES.map((value) => ({ value, text: t(`agentRuns.status.${value}`) })),
]);

/**
 * Read a filter box as a moment in time.
 *
 * `datetime-local` is not used because the Telegram WebView renders it as an
 * unusable spinner, so the box takes `YYYY-MM-DD` or `YYYY-MM-DD HH:MM` in the
 * operator's own timezone. A date without a time means the whole day, which is what
 * "runs since the 1st" has to mean at both ends.
 */
function parseMoment(raw: string, endOfDay: boolean): string | undefined {
  const value = raw.trim();
  if (!value) return undefined;
  const hasTime = value.includes(":") || value.includes("T");
  const normalized = hasTime
    ? value.replace(" ", "T")
    : `${value}T${endOfDay ? "23:59:59" : "00:00:00"}`;
  const moment = new Date(normalized);
  return Number.isNaN(moment.getTime()) ? undefined : moment.toISOString();
}

function parseId(raw: string): number | undefined {
  const value = raw.trim();
  if (!/^-?\d+$/.test(value)) return undefined;
  return Number(value);
}

/**
 * Commit the boxes to the query.
 *
 * Nothing is searched until this runs: the text box matches anywhere inside a run's
 * output or error message, which no index can serve, so following the box as it is
 * typed would scan the table on every pause.
 */
function applyFilters(): void {
  const boxes = form.draft.value;
  applied.value = {
    session_id: boxes.sessionId.trim() || undefined,
    chat_id: parseId(boxes.chatId),
    user_id: parseId(boxes.userId),
    kind: boxes.kind || undefined,
    status: boxes.status || undefined,
    since: parseMoment(boxes.since, false),
    until: parseMoment(boxes.until, true),
    q: boxes.search.trim() || undefined,
  };
  // The boxes are the new baseline: what is on screen is what the list shows.
  form.commit(boxes);
  if (page.value !== 1) {
    // The page watcher reloads, so a filtered list never asks for a page it did not
    // reset - an empty page 4 is indistinguishable from "nothing matched".
    page.value = 1;
    return;
  }
  void runs.reload();
}

/** Drop both the edits and the applied filters. */
function clearFilters(): void {
  form.commit(blank());
  applyFilters();
}

const runs = useAsyncData((signal) =>
  fetchAgentRuns(
    {
      page: page.value,
      size: PAGE_SIZE,
      ...applied.value,
    },
    signal,
  ),
);

useMainButton({
  text: () => t("agentRuns.filters.search"),
  // Always there: searching is an action on this page, not a save, and re-running
  // the same query after new runs arrive is normal.
  visible: () => true,
  enabled: () => !runs.loading.value,
  loading: () => runs.loading.value,
  onClick: applyFilters,
  secondary: {
    text: () => t("agentRuns.filters.reset"),
    visible: () => hasFilters.value || form.isDirty.value,
    onClick: clearFilters,
  },
});

watch(page, () => void runs.reload());

const items = computed(() => runs.data.value?.items ?? []);
const total = computed(() => runs.data.value?.total ?? 0);

/** "OK · out of quota" for a refused run, plain status otherwise. */
function statusText(run: (typeof items.value)[number]): string {
  const label = t(`agentRuns.status.${run.status}`);
  if (run.status !== "rejected" || !run.reject_reason) return label;
  const reason =
    run.reject_reason === "quota" || run.reject_reason === "whitelist"
      ? t(`agentRuns.reject.${run.reject_reason}`)
      : run.reject_reason;
  return `${label} · ${reason}`;
}

function hint(run: (typeof items.value)[number]): string {
  const parts = [formatDateTime(run.started_at), statusText(run)];
  if (run.session_id) {
    // The tail, as one token: the leading characters are the id's timestamp, so
    // sessions a minute apart share them, and a split token cannot be pasted into
    // the filter box (which matches any part of the id).
    parts.push(`${t("agentRuns.session")} ${run.session_id.slice(-8)}`);
  }
  if (run.chat_id !== null || run.user_id !== null) {
    parts.push(`${run.chat_id ?? "-"} / ${run.user_id ?? "-"}`);
  }
  if (run.model_name) parts.push(run.model_name);
  return parts.join(" · ");
}

function open(runId: number): void {
  void router.push({ name: "admin-agent-run", params: { runId: String(runId) } });
}
</script>

<template>
  <PageHeader :title="t('agentRuns.title')" :subtitle="t('agentRuns.subtitle', { total })" />

  <SettingsSection>
    <TextField
      v-model="form.draft.value.sessionId"
      :label="t('agentRuns.filters.sessionId')"
      :placeholder="t('agentRuns.filters.sessionIdPlaceholder')"
      :maxlength="32"
      :changed="form.changedFields.value.includes('sessionId')"
    />
    <TextField
      v-model="form.draft.value.chatId"
      :label="t('agentRuns.filters.chatId')"
      :hint="t('agentRuns.filters.chatIdHint')"
      inputmode="numeric"
      :maxlength="24"
      :changed="form.changedFields.value.includes('chatId')"
    />
    <TextField
      v-model="form.draft.value.userId"
      :label="t('agentRuns.filters.userId')"
      inputmode="numeric"
      :maxlength="24"
      :changed="form.changedFields.value.includes('userId')"
    />
    <SelectField
      v-model="form.draft.value.kind"
      :label="t('agentRuns.filters.kind')"
      :options="kindOptions"
      :changed="form.changedFields.value.includes('kind')"
    />
    <SelectField
      v-model="form.draft.value.status"
      :label="t('agentRuns.filters.status')"
      :options="statusOptions"
      :changed="form.changedFields.value.includes('status')"
    />
    <TextField
      v-model="form.draft.value.since"
      :label="t('agentRuns.filters.since')"
      placeholder="2026-09-01 00:00"
      :maxlength="20"
      :changed="form.changedFields.value.includes('since')"
    />
    <TextField
      v-model="form.draft.value.until"
      :label="t('agentRuns.filters.until')"
      placeholder="2026-09-30"
      :maxlength="20"
      :changed="form.changedFields.value.includes('until')"
    />
    <TextField
      v-model="form.draft.value.search"
      :label="t('agentRuns.filters.search')"
      :placeholder="t('agentRuns.filters.searchPlaceholder')"
      inputmode="search"
      :maxlength="128"
      :changed="form.changedFields.value.includes('search')"
    />
  </SettingsSection>

  <StateBlock
    :loading="runs.loading.value && !runs.data.value"
    :error="runs.error.value"
    :empty="!runs.loading.value && items.length === 0"
    :empty-text="t('agentRuns.empty')"
    @retry="runs.reload"
  >
    <SettingsSection>
      <SettingsRow
        v-for="run in items"
        :key="run.id"
        :label="`#${run.id} · ${t(`agentRuns.kind.${run.kind}`)}`"
        :hint="truncate(hint(run), 120)"
        :value="formatTokens(run.input_tokens + run.output_tokens)"
        navigable
        @click="open(run.id)"
      />
    </SettingsSection>

    <PagerBar v-model:page="page" :size="PAGE_SIZE" :total="total" :loading="runs.loading.value" />
  </StateBlock>
</template>
