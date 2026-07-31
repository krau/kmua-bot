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
import { computed, ref } from "vue";
import { useRouter } from "vue-router";

import { deleteChatPolicy, fetchChatPolicy, setChatPolicy } from "@/api/endpoints/admin";
import { isApiError } from "@/api/errors";
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
import { formatDate } from "@/utils/format";

const props = defineProps<{ chatId: number }>();

const router = useRouter();
const session = useSessionStore();
const { notify, notifyError } = useNotice();

/** Which action is in flight: `agent`, `rss` or `remove`. */
const pending = ref<"agent" | "rss" | "remove" | null>(null);
const busy = computed(() => pending.value !== null);

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
async function setFlag(field: "agent_allowed" | "rss_allowed", value: boolean): Promise<void> {
  if (busy.value || !item.value) return;

  pending.value = field === "agent_allowed" ? "agent" : "rss";
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
