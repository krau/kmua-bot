<script setup lang="ts">
/**
 * One chat's policy, edited in place.
 *
 * This is where a flag lives with its explanation next to its switch. The list
 * page is a directory of chats; it had no room to say what each flag means, so a
 * row of bare toggles was all it could offer - and with the second flag (RSS) it
 * stopped being readable at all.
 *
 * Same honesty rules as the list: a flag is shown with the whitelist mode that
 * gates it, so "on" while the mode is off is labelled as inert rather than implied
 * to mean something. Writes are owner-only server-side; a global admin sees the
 * page read-only.
 */
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { useRouter } from "vue-router";

import { deleteChatPolicy, fetchChatPolicy, setChatPolicy } from "@/api/endpoints/admin";
import { isApiError } from "@/api/errors";
import DefinitionList, { type DefinitionItem } from "@/components/DefinitionList.vue";
import NumberField from "@/components/NumberField.vue";
import PageHeader from "@/components/PageHeader.vue";
import SettingsRow from "@/components/SettingsRow.vue";
import SettingsSection from "@/components/SettingsSection.vue";
import StateBlock from "@/components/StateBlock.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import { useAsyncData } from "@/composables/useAsyncData";
import { useNotice } from "@/composables/useNotice";
import { t, tError } from "@/i18n";
import { useSessionStore } from "@/stores/session";
import { confirm, haptics } from "@/telegram";
import { formatDate, formatNumber, formatTokens } from "@/utils/format";

const props = defineProps<{ chatId: number }>();

const router = useRouter();
const session = useSessionStore();
const { notify, notifyError } = useNotice();

/** Which action is in flight: `agent`, `rss`, `quota` or `remove`. */
const pending = ref<"agent" | "rss" | "quota" | "remove" | null>(null);
/** A debounced numeric write is in flight. */
const saving = ref(false);
const busy = computed(() => pending.value !== null || saving.value);

const detail = useAsyncData((signal) => fetchChatPolicy(props.chatId, signal));

const item = computed(() => detail.data.value?.item ?? null);
const title = computed(() => item.value?.chat_title ?? String(props.chatId));

const agentHint = computed(() =>
  detail.data.value?.agent_whitelist_mode
    ? t("chatPolicy.agentAllowedOn")
    : t("chatPolicy.agentAllowedInert"),
);
const rssHint = computed(() =>
  detail.data.value?.rss_whitelist_mode
    ? t("chatPolicy.rssAllowedOn")
    : t("chatPolicy.rssAllowedInert"),
);

/** Flip one flag. The PUT returns the whole list; the local item is authoritative. */
async function setFlag(
  field: "agent_allowed" | "rss_allowed" | "agent_quota_exempt",
  value: boolean,
): Promise<void> {
  if (busy.value || !item.value) return;

  pending.value = field === "agent_allowed" ? "agent" : field === "rss_allowed" ? "rss" : "quota";
  try {
    await setChatPolicy(props.chatId, { [field]: value });
    if (item.value) item.value.policy[field] = value;
    notify(t("app.saved"));
    haptics.success();
  } catch (error) {
    notifyError(isApiError(error) ? tError(error.code) : t("app.loadFailed"));
    haptics.error();
  } finally {
    pending.value = null;
  }
}

const dailyDraft = ref(0);
const creditsDraft = ref(0);
type QuotaField = "agent_quota_daily_tokens" | "agent_credits";
let saveTimer: ReturnType<typeof setTimeout> | null = null;
/** 待提交的字段 → 值; 两个输入框各改一次都要提交, 所以按字段收。 */
const queued = new Map<QuotaField, number>();

/** 数字字段防抖提交: NumberField 每次按键都会发 update, 直接写会把 "123" 打成三次 PUT。 */
function queueSave(field: QuotaField, value: number): void {
  if (field === "agent_quota_daily_tokens") dailyDraft.value = value;
  else creditsDraft.value = value;
  queued.set(field, value);
  if (saveTimer !== null) clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    saveTimer = null;
    void flushSave();
  }, 800);
}

/** 提交排队的数字修改; 有别的写在飞就等它落地再来一次。 */
async function flushSave(): Promise<void> {
  if (queued.size === 0) return;
  if (pending.value !== null || saving.value) {
    saveTimer = setTimeout(() => {
      saveTimer = null;
      void flushSave();
    }, 300);
    return;
  }
  const writes = [...queued];
  queued.clear();
  saving.value = true;
  try {
    await setChatPolicy(props.chatId, Object.fromEntries(writes));
    const data = detail.data.value;
    if (data) {
      // 用量区块显示的就是这两个值, 不一起更新的话同一屏会自相矛盾。
      for (const [field, value] of writes) {
        if (field === "agent_quota_daily_tokens") {
          data.item.policy.agent_quota_daily_tokens = value;
          data.agent_quota.free_limit_tokens = value;
        } else {
          data.agent_quota.credits = value;
        }
      }
    }
    haptics.success();
  } catch (error) {
    notifyError(isApiError(error) ? tError(error.code) : t("app.loadFailed"));
    haptics.error();
    detail.reload(); // 写失败时把草稿拉回服务端的值
  } finally {
    saving.value = false;
  }
}

onBeforeUnmount(() => {
  if (saveTimer !== null) clearTimeout(saveTimer);
  saveTimer = null;
  // 行已经被删掉了, 排队中的数字改动没有可写的地方; 丢掉它也就不会让 flushSave 卡在
  // pending === "remove" 上把重试定时器一直挂下去。
  if (pending.value === "remove") {
    queued.clear();
    return;
  }
  void flushSave();
});

// 载入/重载后把草稿对齐到服务端的值。
watch(
  () => detail.data.value,
  (data) => {
    if (!data) return;
    dailyDraft.value = data.item.policy.agent_quota_daily_tokens;
    creditsDraft.value = data.agent_quota.credits;
  },
  { immediate: true },
);

const usageItems = computed<DefinitionItem[]>(() => {
  const quota = detail.data.value?.agent_quota;
  if (!quota) return [];
  return [
    { label: t("admin.agentUsedToday"), value: formatNumber(quota.requests_today) },
    {
      label: t("chatPolicy.quotaDaily"),
      value:
        quota.free_limit_tokens === 0
          ? t("chatPolicy.quotaDailyNone")
          : `${formatTokens(quota.free_used_tokens_today)} / ${formatTokens(quota.free_limit_tokens ?? 0)}`,
    },
    { label: t("chatPolicy.quotaCredits"), value: formatTokens(quota.credits) },
    {
      label: t("admin.agentTokensToday"),
      value: `${formatTokens(quota.input_tokens_today)} / ${formatTokens(quota.output_tokens_today)}`,
    },
  ];
});

async function remove(): Promise<void> {
  const ok = await confirm({
    title: t("chatPolicy.remove"),
    message: t("chatPolicy.removeConfirm", { name: title.value }),
    confirmText: t("chatPolicy.remove"),
    destructive: true,
  });
  if (!ok) return;

  pending.value = "remove";
  try {
    await deleteChatPolicy(props.chatId);
    notify(t("chatPolicy.removed"));
    haptics.success();
    void router.push({ name: "admin-chat-policies" });
  } catch (error) {
    notifyError(isApiError(error) ? tError(error.code) : t("app.loadFailed"));
    haptics.error();
    pending.value = null;
  }
}
</script>

<template>
  <PageHeader :title="title" :subtitle="String(props.chatId)" />

  <StateBlock
    :loading="detail.loading.value && !detail.data.value"
    :error="detail.error.value"
    @retry="detail.reload"
  >
    <SettingsSection :label="t('chatPolicy.policies')">
      <SettingsRow :label="t('chatPolicy.agentAllowed')" :hint="agentHint" :disabled="busy">
        <template #control>
          <ToggleSwitch
            :model-value="item?.policy.agent_allowed ?? false"
            :disabled="!session.isOwner || busy"
            :busy="pending === 'agent'"
            :aria-label="t('chatPolicy.agentAllowed')"
            @update:model-value="setFlag('agent_allowed', $event)"
          />
        </template>
      </SettingsRow>
      <SettingsRow :label="t('chatPolicy.rssAllowed')" :hint="rssHint" :disabled="busy">
        <template #control>
          <ToggleSwitch
            :model-value="item?.policy.rss_allowed ?? false"
            :disabled="!session.isOwner || busy"
            :busy="pending === 'rss'"
            :aria-label="t('chatPolicy.rssAllowed')"
            @update:model-value="setFlag('rss_allowed', $event)"
          />
        </template>
      </SettingsRow>
    </SettingsSection>

    <!-- 私聊没有群账户, 额度字段后端一律拒绝。 -->
    <SettingsSection
      v-if="props.chatId < 0"
      :label="t('chatPolicy.quota')"
      :hint="t('chatPolicy.quotaHint')"
    >
      <SettingsRow
        :label="t('chatPolicy.quotaExempt')"
        :hint="t('chatPolicy.quotaExemptHint')"
        :disabled="busy"
      >
        <template #control>
          <ToggleSwitch
            :model-value="item?.policy.agent_quota_exempt ?? false"
            :disabled="!session.isOwner || busy"
            :busy="pending === 'quota'"
            :aria-label="t('chatPolicy.quotaExempt')"
            @update:model-value="setFlag('agent_quota_exempt', $event)"
          />
        </template>
      </SettingsRow>
      <NumberField
        v-model="dailyDraft"
        :label="t('chatPolicy.quotaDaily')"
        :hint="t('chatPolicy.quotaDailyHint')"
        :disabled="!session.isOwner || busy"
        @update:model-value="queueSave('agent_quota_daily_tokens', $event)"
      />
      <NumberField
        v-model="creditsDraft"
        :label="t('chatPolicy.quotaCredits')"
        :disabled="!session.isOwner || busy"
        @update:model-value="queueSave('agent_credits', $event)"
      />
    </SettingsSection>

    <SettingsSection
      v-if="props.chatId < 0 && detail.data.value?.agent_quota"
      :label="t('chatPolicy.quotaUsage')"
    >
      <DefinitionList :items="usageItems" />
    </SettingsSection>

    <SettingsSection v-if="item?.note" :label="t('chatPolicy.noteLabel')">
      <SettingsRow :label="item.note" :value="formatDate(item.created_at)" />
    </SettingsSection>

    <!-- Writes are owner-only server-side, so a global admin is not shown a form
         that would be refused. -->
    <SettingsSection v-if="session.isOwner" :hint="t('chatPolicy.removeHint')">
      <SettingsRow
        :label="t('chatPolicy.remove')"
        navigable
        destructive
        :disabled="busy"
        :busy="pending === 'remove'"
        @click="remove"
      />
    </SettingsSection>
  </StateBlock>
</template>
