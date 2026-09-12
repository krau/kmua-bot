<script setup lang="ts">
/**
 * Recorded agent runs, most recent first.
 *
 * Read-only on purpose: these rows describe what the bot did, and an operator who
 * could edit them would no longer be reading a record. Filters are committed with a
 * button rather than on every keystroke, because three of them are free-form ids and
 * dates - reloading on each character would query a half-typed id on every tick.
 */
import { computed, ref, watch } from "vue";
import { useRouter } from "vue-router";

import { fetchAgentRuns } from "@/api/endpoints/admin";
import type { AgentRunKind, AgentRunStatus } from "@/api/types";
import PageHeader from "@/components/PageHeader.vue";
import PagerBar from "@/components/PagerBar.vue";
import SelectField from "@/components/SelectField.vue";
import SettingsRow from "@/components/SettingsRow.vue";
import SettingsSection from "@/components/SettingsSection.vue";
import StateBlock from "@/components/StateBlock.vue";
import TextField from "@/components/TextField.vue";
import { useAsyncData } from "@/composables/useAsyncData";
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

const router = useRouter();
const page = ref(1);

/** Edited filter values; copied into `applied` when the operator commits. */
const chatId = ref("");
const userId = ref("");
const kind = ref("");
const status = ref("");
const since = ref("");
const until = ref("");
const search = ref("");

interface Applied {
  chatId?: number;
  userId?: number;
  kind?: string;
  status?: string;
  since?: string;
  until?: string;
  q?: string;
}

const applied = ref<Applied>({});

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

function applyFilters(): void {
  applied.value = {
    chatId: parseId(chatId.value),
    userId: parseId(userId.value),
    kind: kind.value || undefined,
    status: status.value || undefined,
    since: parseMoment(since.value, false),
    until: parseMoment(until.value, true),
    q: search.value.trim() || undefined,
  };
  if (page.value !== 1) {
    page.value = 1;
    return;
  }
  void runs.reload();
}

function resetFilters(): void {
  chatId.value = "";
  userId.value = "";
  kind.value = "";
  status.value = "";
  since.value = "";
  until.value = "";
  search.value = "";
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
      v-model="chatId"
      :label="t('agentRuns.filters.chatId')"
      inputmode="numeric"
      :maxlength="24"
    />
    <TextField
      v-model="userId"
      :label="t('agentRuns.filters.userId')"
      inputmode="numeric"
      :maxlength="24"
    />
    <SelectField v-model="kind" :label="t('agentRuns.filters.kind')" :options="kindOptions" />
    <SelectField v-model="status" :label="t('agentRuns.filters.status')" :options="statusOptions" />
    <TextField
      v-model="since"
      :label="t('agentRuns.filters.since')"
      placeholder="2026-09-01 00:00"
      :maxlength="20"
    />
    <TextField
      v-model="until"
      :label="t('agentRuns.filters.until')"
      placeholder="2026-09-30"
      :maxlength="20"
    />
    <TextField
      v-model="search"
      :label="t('agentRuns.filters.search')"
      :placeholder="t('agentRuns.filters.searchPlaceholder')"
      inputmode="search"
      :maxlength="128"
    />
  </SettingsSection>

  <div class="mb-section flex gap-related px-related">
    <button
      type="button"
      class="text-accent dark:text-accent-dark text-sub underline"
      @click="applyFilters"
    >
      {{ t("agentRuns.filters.apply") }}
    </button>
    <button type="button" class="text-hint text-sub underline" @click="resetFilters">
      {{ t("agentRuns.filters.reset") }}
    </button>
  </div>

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
