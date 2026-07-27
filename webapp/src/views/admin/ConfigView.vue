<script setup lang="ts">
/**
 * The running configuration, read-only.
 *
 * Secrets arrive already replaced by a marker server-side, so this page renders
 * "configured" or "not set" and never a value. Field names and JSON-ish values use
 * the monospace face - they are identifiers, which is the one place monospace earns
 * its keep in this UI.
 *
 * Reload is owner-only and takes effect immediately, so it asks first and says what
 * it will change.
 */
import { computed, ref } from "vue";

import { fetchConfig, reloadConfig } from "@/api/endpoints/admin";
import { isApiError } from "@/api/errors";
import type { ConfigValue } from "@/api/types";
import DefinitionList, { type DefinitionItem } from "@/components/DefinitionList.vue";
import PageHeader from "@/components/PageHeader.vue";
import SettingsRow from "@/components/SettingsRow.vue";
import SettingsSection from "@/components/SettingsSection.vue";
import StateBlock from "@/components/StateBlock.vue";
import { useAsyncData } from "@/composables/useAsyncData";
import { useNotice } from "@/composables/useNotice";
import { t, tError } from "@/i18n";
import { useSessionStore } from "@/stores/session";
import { confirm, haptics } from "@/telegram";

const session = useSessionStore();

const changedFields = ref<string[]>([]);
const reloading = ref(false);
const { notify, notifyError } = useNotice();

const config = useAsyncData((signal) => fetchConfig(signal));

function renderValue(value: ConfigValue): string {
  if (value === null) return t("app.none");
  if (typeof value === "boolean") return value ? t("app.yes") : t("app.no");
  if (Array.isArray(value)) return value.length ? value.join(", ") : t("app.none");
  if (value === "") return t("app.none");
  return String(value);
}

const groups = computed(() => {
  const data = config.data.value;
  if (!data) return [];
  return Object.entries(data.groups).map(([name, fields]) => ({
    name,
    items: Object.entries(fields).map<DefinitionItem>(([key, value]) => ({
      label: key,
      value: renderValue(value),
      mono: true,
      muted: value === null || value === "",
    })),
  }));
});

const secrets = computed<DefinitionItem[]>(() => {
  const data = config.data.value;
  if (!data) return [];
  return Object.entries(data.secrets).map(([key, value]) => ({
    label: key,
    value: value === null ? t("admin.notConfigured") : t("admin.configured"),
    mono: true,
    muted: value === null,
  }));
});

const providers = computed<DefinitionItem[]>(() => {
  const data = config.data.value;
  if (!data) return [];
  return Object.entries(data.agent_providers).map(([name, provider]) => ({
    label: name,
    value: `${provider.url ?? "-"} · ${
      provider.key === null ? t("admin.notConfigured") : t("admin.configured")
    }`,
    mono: true,
  }));
});

async function onReload(): Promise<void> {
  const ok = await confirm({
    title: t("admin.reload"),
    message: t("admin.reloadConfirm"),
    confirmText: t("admin.reload"),
    destructive: true,
  });
  if (!ok) return;

  reloading.value = true;
  changedFields.value = [];
  try {
    const result = await reloadConfig();
    if (!result.success) {
      notifyError(`${t("admin.reloadFailed")}: ${result.message}`);
      haptics.error();
      return;
    }
    changedFields.value = result.changed_fields;
    notify(
      result.changed_fields.length
        ? t("admin.reloadDone", { count: result.changed_fields.length })
        : t("admin.reloadNoChange"),
    );
    haptics.success();
    await config.reload();
  } catch (error) {
    notifyError(isApiError(error) ? tError(error.code) : t("app.loadFailed"));
    haptics.error();
  } finally {
    reloading.value = false;
  }
}
</script>

<template>
  <PageHeader :title="t('admin.config')" :subtitle="t('admin.configHint')" />

  <StateBlock
    :loading="config.loading.value && !config.data.value"
    :error="config.error.value"
    @retry="config.reload"
  >
    <SettingsSection v-if="changedFields.length" :label="t('admin.changedFields')">
      <p class="px-related py-tight font-mono text-note text-hint">
        {{ changedFields.join(", ") }}
      </p>
    </SettingsSection>

    <SettingsSection v-if="session.isOwner">
      <SettingsRow
        :label="t('admin.reload')"
        :hint="reloading ? t('app.working') : undefined"
        navigable
        destructive
        :busy="reloading"
        @click="onReload"
      />
    </SettingsSection>

    <SettingsSection v-for="group in groups" :key="group.name" :label="group.name">
      <DefinitionList :items="group.items" />
    </SettingsSection>

    <SettingsSection :label="t('admin.providers')">
      <DefinitionList :items="providers" />
    </SettingsSection>

    <SettingsSection label="secrets">
      <DefinitionList :items="secrets" />
    </SettingsSection>

    <SettingsSection>
      <DefinitionList
        :items="[{ label: t('admin.owners'), value: config.data.value?.owners_count ?? 0 }]"
      />
    </SettingsSection>
  </StateBlock>
</template>
