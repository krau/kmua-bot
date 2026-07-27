<script setup lang="ts">
/**
 * Which admin rights the /t command grants.
 *
 * Its own page rather than a section of the config page, for two reasons: the API
 * stores it under a separate endpoint, and twelve more switches on an already long
 * page buries the settings people actually came for.
 *
 * The payload is the complete desired state - unlisted keys are false - so what is
 * on screen is exactly what gets saved.
 */
import { ref } from "vue";

import { fetchChat, saveTitlePermissions } from "@/api/endpoints/chats";
import { isApiError } from "@/api/errors";
import PageHeader from "@/components/PageHeader.vue";
import SettingsRow from "@/components/SettingsRow.vue";
import SettingsSection from "@/components/SettingsSection.vue";
import StateBlock from "@/components/StateBlock.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import { useAsyncData } from "@/composables/useAsyncData";
import { useDirtyState } from "@/composables/useDirtyState";
import { useMainButton } from "@/composables/useMainButton";
import { useNotice } from "@/composables/useNotice";
import { t, tError } from "@/i18n";
import { haptics } from "@/telegram";
import { TITLE_PERMISSION_KEYS } from "./config-layout";

const props = defineProps<{ chatId: number }>();

const saving = ref(false);
const { notify, notifyError } = useNotice();

function blank(): Record<string, boolean> {
  return Object.fromEntries(TITLE_PERMISSION_KEYS.map((key) => [key, false]));
}

const form = useDirtyState<Record<string, boolean>>(blank());

const chat = useAsyncData(async (signal) => {
  const detail = await fetchChat(props.chatId, signal);
  form.commit({ ...blank(), ...detail.config.title_permissions });
  return detail;
});

async function save(): Promise<void> {
  saving.value = true;
  try {
    const saved = await saveTitlePermissions(props.chatId, form.draft.value);
    form.commit({ ...blank(), ...saved.title_permissions });
    notify(t("app.saved"));
    haptics.success();
  } catch (error) {
    notifyError(isApiError(error) ? tError(error.code) : t("app.loadFailed"));
    haptics.error();
  } finally {
    saving.value = false;
  }
}

useMainButton({
  text: () => t("app.saveCount", { count: form.changedFields.value.length }),
  visible: () => form.isDirty.value,
  enabled: () => form.isDirty.value && !saving.value,
  loading: () => saving.value,
  onClick: () => void save(),
  secondary: {
    text: () => t("app.reset"),
    visible: () => form.isDirty.value,
    onClick: () => form.reset(),
  },
});
</script>

<template>
  <PageHeader :title="t('chats.titlePermissions')" :subtitle="chat.data.value?.title" />

  <StateBlock
    :loading="chat.loading.value && !chat.data.value"
    :error="chat.error.value"
    @retry="chat.reload"
  >
    <SettingsSection :hint="t('chats.titlePermissionsHint')">
      <SettingsRow
        v-for="key in TITLE_PERMISSION_KEYS"
        :key="key"
        :label="t(`titlePermissions.${key}`)"
        :changed="form.changedFields.value.includes(key)"
      >
        <template #control>
          <ToggleSwitch
            v-model="form.draft.value[key] as boolean"
            :aria-label="t(`titlePermissions.${key}`)"
          />
        </template>
      </SettingsRow>
    </SettingsSection>
  </StateBlock>
</template>
