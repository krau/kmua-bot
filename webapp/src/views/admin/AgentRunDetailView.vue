<script setup lang="ts">
/**
 * One recorded run: how it ended, and every step it took.
 *
 * The steps are loaded one at a time and only when opened. A turn can hold a
 * couple of hundred events and the largest of them carry a full message history,
 * so fetching them all up front would send the whole transcript to render a
 * timeline that is mostly headers.
 *
 * The conversation view is the readable form of a request or response; the raw
 * JSON underneath is the same data untouched, for when the readable form is not
 * the question.
 */
import { computed, ref } from "vue";

import { fetchAgentRun, fetchAgentRunEvent } from "@/api/endpoints/admin";
import type { AgentRunEventDetail } from "@/api/types";
import { isApiError } from "@/api/errors";
import DefinitionList, { type DefinitionItem } from "@/components/DefinitionList.vue";
import PageHeader from "@/components/PageHeader.vue";
import SettingsRow from "@/components/SettingsRow.vue";
import SettingsSection from "@/components/SettingsSection.vue";
import StateBlock from "@/components/StateBlock.vue";
import { useAsyncData } from "@/composables/useAsyncData";
import { t, tError } from "@/i18n";
import { formatDateTime, formatNumber, truncate } from "@/utils/format";
import { traceBlocks } from "@/utils/traceMessages";

const props = defineProps<{ runId: number }>();

const detail = useAsyncData((signal) => fetchAgentRun(props.runId, signal));
const run = computed(() => detail.data.value);

const openSeq = ref<number | null>(null);
const event = ref<AgentRunEventDetail | null>(null);
const eventLoading = ref(false);
const eventError = ref<string | null>(null);
/** Which form of a message event is shown: the conversation, or its JSON. */
const showRaw = ref(false);

const events = computed(() => run.value?.events ?? []);

const blocks = computed(() => traceBlocks(event.value?.messages ?? []));

const payloadJson = computed(() => JSON.stringify(event.value?.payload ?? null, null, 2));

const instructionsJson = computed(() => {
  const payload = event.value?.payload;
  const parts = payload?.["instruction_parts"];
  return parts === undefined || parts === null ? null : JSON.stringify(parts, null, 2);
});

const settingsJson = computed(() => {
  const payload = event.value?.payload;
  const settings = payload?.["model_settings"];
  return settings === undefined ? null : JSON.stringify(settings, null, 2);
});

async function toggle(seq: number): Promise<void> {
  if (openSeq.value === seq) {
    openSeq.value = null;
    event.value = null;
    return;
  }
  openSeq.value = seq;
  event.value = null;
  eventError.value = null;
  showRaw.value = false;
  eventLoading.value = true;
  try {
    const loaded = await fetchAgentRunEvent(props.runId, seq);
    // A second tap while the first request was in flight wins; the stale answer
    // must not overwrite the step the operator is now looking at.
    if (openSeq.value === seq) event.value = loaded;
  } catch (error) {
    if (openSeq.value === seq) {
      eventError.value = isApiError(error) ? tError(error.code) : t("app.loadFailed");
    }
  } finally {
    if (openSeq.value === seq) eventLoading.value = false;
  }
}

function eventHint(row: (typeof events.value)[number]): string {
  const parts: string[] = [];
  if (row.name) parts.push(row.name);
  if (row.payload_chars !== null) parts.push(`${formatNumber(row.payload_chars)} chars`);
  if (row.status !== "ok") parts.push(row.status);
  return parts.join(" · ");
}

function summaryItems(data: NonNullable<typeof run.value>): DefinitionItem[] {
  const rows: DefinitionItem[] = [
    { label: t("agentRuns.columns.run"), value: data.id, mono: true },
    { label: t("agentRuns.columns.kind"), value: t(`agentRuns.kind.${data.kind}`) },
    { label: t("agentRuns.columns.status"), value: t(`agentRuns.status.${data.status}`) },
  ];
  if (data.reject_reason) {
    rows.push({ label: t("agentRuns.reject.label"), value: data.reject_reason, mono: true });
  }
  rows.push(
    { label: t("agentRuns.columns.startedAt"), value: formatDateTime(data.started_at) },
    { label: t("agentRuns.columns.durationMs"), value: formatNumber(data.duration_ms), mono: true },
    {
      label: t("agentRuns.columns.chat"),
      value: data.chat_id ?? "-",
      mono: true,
      muted: data.chat_id === null,
    },
    {
      label: t("agentRuns.columns.user"),
      value: data.user_id ?? "-",
      mono: true,
      muted: data.user_id === null,
    },
  );
  if (data.message_id !== null) {
    rows.push({ label: t("agentRuns.columns.messageId"), value: data.message_id, mono: true });
  }
  if (data.parent_run_id !== null) {
    rows.push({ label: t("agentRuns.columns.parent"), value: data.parent_run_id, mono: true });
  }
  rows.push(
    {
      label: t("agentRuns.columns.model"),
      value: data.model_name ?? "-",
      mono: true,
      muted: data.model_name === null,
    },
    {
      label: t("agentRuns.detail.modelRole"),
      value: data.model_role ? t(`agentRuns.roles.${data.model_role}`) : "-",
      muted: data.model_role === null,
    },
    {
      label: t("agentRuns.detail.streaming"),
      value: data.streaming ? t("app.yes") : t("app.no"),
    },
    {
      label: t("agentRuns.columns.requests"),
      value: `${data.requests} / ${data.tool_calls}`,
      mono: true,
    },
    {
      label: t("agentRuns.columns.tokens"),
      value: `${formatNumber(data.input_tokens)} / ${formatNumber(data.output_tokens)}`,
      mono: true,
    },
    {
      label: t("agentRuns.columns.events"),
      value: `${data.event_count} (+${data.events_dropped})`,
      mono: true,
    },
  );
  if (data.cache_read_tokens || data.cache_write_tokens) {
    rows.push({
      label: t("agentRuns.detail.cacheTokens"),
      value: `${formatNumber(data.cache_read_tokens)} / ${formatNumber(data.cache_write_tokens)}`,
      mono: true,
    });
  }
  if (data.output_kind) {
    rows.push({ label: t("agentRuns.detail.outputKind"), value: data.output_kind, mono: true });
  }
  if (data.output_chars !== null) {
    rows.push({
      label: t("agentRuns.detail.outputChars"),
      value: formatNumber(data.output_chars),
      mono: true,
    });
  }
  if (data.error_class) {
    rows.push({ label: t("agentRuns.detail.error"), value: data.error_class, mono: true });
  }
  return rows;
}
</script>

<template>
  <PageHeader :title="t('agentRuns.detail.title', { id: runId })" />

  <StateBlock
    :loading="detail.loading.value && !run"
    :error="detail.error.value"
    @retry="detail.reload"
  >
    <template v-if="run">
      <SettingsSection :label="t('agentRuns.detail.summary')">
        <DefinitionList :items="summaryItems(run)" />
      </SettingsSection>

      <SettingsSection v-if="run.output_text" :label="t('agentRuns.detail.output')">
        <p class="bg-bg whitespace-pre-wrap break-words px-related py-related text-sub">
          {{ run.output_text }}
        </p>
      </SettingsSection>

      <SettingsSection v-if="run.error_message" :label="t('agentRuns.detail.error')">
        <p
          class="bg-bg text-danger dark:text-danger-dark whitespace-pre-wrap break-words px-related py-related font-mono text-note"
        >
          {{ run.error_message }}
        </p>
      </SettingsSection>

      <SettingsSection :label="t('agentRuns.detail.events')">
        <p v-if="events.length === 0" class="px-related py-related text-sub text-hint">
          {{ t("agentRuns.detail.emptyEvents") }}
        </p>
        <template v-for="row in events" :key="row.seq">
          <SettingsRow
            :label="`#${row.seq} · ${t(`agentRuns.eventKind.${row.kind}`)}`"
            :hint="truncate(eventHint(row), 100)"
            :value="row.duration_ms === null ? null : `${formatNumber(row.duration_ms)} ms`"
            navigable
            @click="toggle(row.seq)"
          />
          <div
            v-if="openSeq === row.seq"
            class="border-line border-b px-related py-related last:border-b-0"
          >
            <p v-if="eventLoading" class="text-sub text-hint">{{ t("app.loading") }}</p>
            <p v-else-if="eventError" class="text-sub text-danger dark:text-danger-dark">
              {{ eventError }}
            </p>
            <template v-else-if="event">
              <p v-if="event.truncated" class="mb-tight text-note text-hint">
                {{ t("agentRuns.detail.truncated") }}
              </p>

              <template v-if="event.kind === 'model_request' || event.kind === 'model_response'">
                <div class="mb-related flex gap-related">
                  <button
                    type="button"
                    class="text-sub underline"
                    :class="showRaw ? 'text-hint' : 'text-accent dark:text-accent-dark'"
                    @click="showRaw = false"
                  >
                    {{ t("agentRuns.detail.conversation") }}
                  </button>
                  <button
                    type="button"
                    class="text-sub underline"
                    :class="showRaw ? 'text-accent dark:text-accent-dark' : 'text-hint'"
                    @click="showRaw = true"
                  >
                    {{ t("agentRuns.detail.rawJson") }}
                  </button>
                </div>

                <template v-if="event.kind === 'model_request' && !showRaw">
                  <div v-if="instructionsJson" class="mb-related">
                    <p class="mb-tight text-note text-hint">
                      {{ t("agentRuns.detail.instructions") }}
                    </p>
                    <pre
                      class="bg-bg rounded-container overflow-x-auto px-related py-related font-mono text-note whitespace-pre-wrap break-all"
                      >{{ instructionsJson }}</pre>
                  </div>
                  <div v-if="settingsJson" class="mb-related">
                    <p class="mb-tight text-note text-hint">
                      {{ t("agentRuns.detail.settings") }}
                    </p>
                    <pre
                      class="bg-bg rounded-container overflow-x-auto px-related py-related font-mono text-note whitespace-pre-wrap break-all"
                      >{{ settingsJson }}</pre>
                  </div>
                </template>

                <p v-if="event.messages === null && !showRaw" class="text-sub text-hint">
                  {{ t("agentRuns.detail.unreconstructable") }}
                </p>

                <div v-else-if="!showRaw" class="flex flex-col gap-related">
                  <div v-for="(block, index) in blocks" :key="index">
                    <p class="mb-tight text-note text-hint">
                      {{ t(`agentRuns.detail.role.${block.role}`)
                      }}<template v-if="block.toolName"> · {{ block.toolName }}</template>
                    </p>
                    <pre
                      class="bg-bg rounded-container overflow-x-auto px-related py-related whitespace-pre-wrap break-all"
                      :class="
                        block.kind === 'tool-call' || block.kind === 'tool-return'
                          ? 'font-mono text-note'
                          : 'text-sub'
                      "
                      >{{ block.text }}</pre>
                  </div>
                </div>

                <pre
                  v-if="showRaw"
                  class="bg-bg rounded-container overflow-x-auto px-related py-related font-mono text-note whitespace-pre-wrap break-all"
                  >{{ payloadJson }}</pre>
              </template>

              <pre
                v-else
                class="bg-bg rounded-container overflow-x-auto px-related py-related font-mono text-note whitespace-pre-wrap break-all"
                >{{ payloadJson }}</pre>
            </template>
          </div>
        </template>
      </SettingsSection>
    </template>
  </StateBlock>
</template>
