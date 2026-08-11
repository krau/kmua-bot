<script setup lang="ts">
/**
 * Edit a user record.
 *
 * An editable definition list: name on the left, value on the right, edited in place.
 * Changed fields get a 2px accent bar on the left - a real signal that this row has an
 * unsaved edit, not a decorative coloured border.
 *
 * Owner-only fields (coins, affection, global admin) are rendered as read-only for a
 * global admin with a note saying why, rather than hidden. Hiding them would make the
 * permission boundary invisible and the page look different for different people with
 * no explanation.
 *
 * The API applies what it can and reports the rest in `skipped`, so a mixed edit gives
 * partial success plus an exact list of what was refused.
 */
import { computed, ref } from "vue";

import { systemInfo } from "@/api/endpoints/auth";
import { blockUser, fetchUser, unblockUser, updateUser } from "@/api/endpoints/admin";
import { isApiError } from "@/api/errors";
import type { AdminUserPatch } from "@/api/types";
import DefinitionList, { type DefinitionItem } from "@/components/DefinitionList.vue";
import NumberField from "@/components/NumberField.vue";
import PageHeader from "@/components/PageHeader.vue";
import SelectField from "@/components/SelectField.vue";
import SettingsRow from "@/components/SettingsRow.vue";
import SettingsSection from "@/components/SettingsSection.vue";
import StateBlock from "@/components/StateBlock.vue";
import TextField from "@/components/TextField.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import { useAsyncData } from "@/composables/useAsyncData";
import { useDirtyState } from "@/composables/useDirtyState";
import { useMainButton } from "@/composables/useMainButton";
import { useNotice } from "@/composables/useNotice";
import { t, tError } from "@/i18n";
import { useSessionStore } from "@/stores/session";
import { confirm, haptics } from "@/telegram";
import { formatDateTime, formatNumber } from "@/utils/format";
import { localeName } from "@/utils/locale";

const props = defineProps<{ userId: number }>();

const session = useSessionStore();
const saving = ref(false);
const blocking = ref(false);
const { notify, notifyError } = useNotice();

interface EditableUser extends Record<string, unknown> {
  full_name: string;
  username: string;
  lang: string;
  waifu_mention: boolean;
  coins: number;
  affection: number;
  is_bot_global_admin: boolean;
}

const form = useDirtyState<EditableUser>({
  full_name: "",
  username: "",
  lang: "zh-CN",
  waifu_mention: false,
  coins: 0,
  affection: 0,
  is_bot_global_admin: false,
});

const user = useAsyncData(async (signal) => {
  const data = await fetchUser(props.userId, signal);
  form.commit({
    full_name: data.full_name,
    username: data.username ?? "",
    lang: data.lang,
    waifu_mention: data.waifu_mention,
    coins: data.coins,
    affection: data.affection,
    is_bot_global_admin: data.is_bot_global_admin,
  });
  return data;
});

const locales = useAsyncData(async (signal) => (await systemInfo(signal)).available_locales);
const localeOptions = computed(() =>
  (locales.data.value ?? [form.draft.value.lang]).map((value) => ({
    value,
    text: localeName(value),
  })),
);

/** Coins and affection move the economy and the ranking, so they need owner. */
const canEditEconomy = computed(() => session.isOwner);
/** Changing your own role could lock the operator out, so the API refuses it too. */
const canEditRole = computed(() => session.isOwner && props.userId !== session.user?.id);

const readonlyItems = computed<DefinitionItem[]>(() => {
  const data = user.data.value;
  if (!data) return [];
  const items: DefinitionItem[] = [
    { label: t("me.id"), value: data.id, mono: true },
    { label: t("admin.created"), value: formatDateTime(data.created_at) },
    { label: t("me.quotes"), value: data.quote_count },
    { label: t("me.gifts"), value: data.gift_count },
    { label: t("admin.joinedChats"), value: data.chats.length },
  ];
  if (data.is_owner) items.push({ label: t("admin.isOwner"), value: t("app.yes") });
  if (data.is_bot) items.push({ label: t("admin.isBot"), value: t("app.yes") });
  if (data.is_married) {
    items.push({
      label: t("me.marriedTo"),
      value: data.married_waifu_id ?? t("app.none"),
      mono: true,
    });
  }
  return items;
});

function changed(field: string): boolean {
  return form.changedFields.value.includes(field);
}

/** Send only what actually changed, so the audit log records real transitions. */
function buildPatch(): AdminUserPatch {
  const patch: AdminUserPatch = {};
  const draft = form.draft.value;
  if (changed("full_name")) patch.full_name = draft.full_name;
  if (changed("username")) patch.username = draft.username;
  if (changed("lang")) patch.lang = draft.lang;
  if (changed("waifu_mention")) patch.waifu_mention = draft.waifu_mention;
  if (changed("coins")) patch.coins = draft.coins;
  if (changed("affection")) patch.affection = draft.affection;
  if (changed("is_bot_global_admin")) patch.is_bot_global_admin = draft.is_bot_global_admin;
  return patch;
}

async function save(): Promise<void> {
  const patch = buildPatch();
  if (Object.keys(patch).length === 0) {
    notify(t("admin.noChanges"));
    return;
  }

  // Granting or revoking bot-wide admin rights deserves a deliberate confirmation.
  if (patch.is_bot_global_admin !== undefined) {
    const ok = await confirm({
      title: t("admin.globalAdmin"),
      message: t("admin.roleChangeConfirm", {
        name: user.data.value?.full_name ?? String(props.userId),
      }),
      confirmText: t("app.confirm"),
      destructive: true,
    });
    if (!ok) return;
  }

  saving.value = true;
  try {
    const result = await updateUser(props.userId, patch);
    user.data.value = result.user;
    form.commit({
      full_name: result.user.full_name,
      username: result.user.username ?? "",
      lang: result.user.lang,
      waifu_mention: result.user.waifu_mention,
      coins: result.user.coins,
      affection: result.user.affection,
      is_bot_global_admin: result.user.is_bot_global_admin,
    });

    const parts = [t("admin.changesApplied", { count: result.changed.length })];
    if (result.skipped.length) {
      parts.push(t("admin.changesSkipped", { count: result.skipped.length }));
    }
    notify(parts.join(" · "));
    haptics.success();
  } catch (error) {
    notifyError(isApiError(error) ? tError(error.code) : t("app.loadFailed"));
    haptics.error();
  } finally {
    saving.value = false;
  }
}

async function onToggleBlock(): Promise<void> {
  const blocked = user.data.value?.is_blocked ?? false;
  const ok = await confirm({
    title: t(blocked ? "admin.unblockUser" : "admin.blockUser"),
    message: t(blocked ? "admin.unblockUserConfirm" : "admin.blockUserConfirm"),
    confirmText: t(blocked ? "admin.unblockUser" : "admin.blockUser"),
    destructive: !blocked,
  });
  if (!ok) return;

  blocking.value = true;
  try {
    if (blocked) {
      await unblockUser(props.userId);
    } else {
      await blockUser(props.userId);
    }
    haptics.success();
    notify(t(blocked ? "admin.unblockUserDone" : "admin.blockUserDone"));
    user.reload();
  } catch (error) {
    notifyError(isApiError(error) ? tError(error.code) : t("app.loadFailed"));
    haptics.error();
  } finally {
    blocking.value = false;
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
  <PageHeader :title="t('admin.editUser')" :subtitle="user.data.value?.full_name" />

  <StateBlock
    :loading="user.loading.value && !user.data.value"
    :error="user.error.value"
    @retry="user.reload"
  >
    <SettingsSection :label="t('me.profile')">
      <TextField
        v-model="form.draft.value.full_name"
        :label="t('admin.fullName')"
        :maxlength="256"
        :changed="changed('full_name')"
      />
      <TextField
        v-model="form.draft.value.username"
        :label="t('me.username')"
        :maxlength="64"
        :changed="changed('username')"
      />
      <SelectField
        v-model="form.draft.value.lang"
        :label="t('me.lang')"
        :options="localeOptions"
        :changed="changed('lang')"
      />
      <SettingsRow :label="t('me.waifuMention')" :changed="changed('waifu_mention')">
        <template #control>
          <ToggleSwitch
            v-model="form.draft.value.waifu_mention"
            :aria-label="t('me.waifuMention')"
          />
        </template>
      </SettingsRow>
    </SettingsSection>

    <SettingsSection
      :label="t('me.economy')"
      :hint="canEditEconomy ? undefined : t('admin.ownerOnly')"
    >
      <NumberField
        v-if="canEditEconomy"
        v-model="form.draft.value.coins"
        :label="t('me.coins')"
        :changed="changed('coins')"
      />
      <SettingsRow v-else :label="t('me.coins')" :value="formatNumber(form.draft.value.coins)" />

      <NumberField
        v-if="canEditEconomy"
        v-model="form.draft.value.affection"
        :label="t('me.affection')"
        :changed="changed('affection')"
      />
      <SettingsRow
        v-else
        :label="t('me.affection')"
        :value="formatNumber(form.draft.value.affection)"
      />
    </SettingsSection>

    <SettingsSection :label="canEditRole ? undefined : t('admin.ownerOnly')">
      <SettingsRow
        :label="t('admin.globalAdmin')"
        :changed="changed('is_bot_global_admin')"
        :disabled="!canEditRole"
      >
        <template #control>
          <ToggleSwitch
            v-model="form.draft.value.is_bot_global_admin"
            :disabled="!canEditRole"
            :aria-label="t('admin.globalAdmin')"
          />
        </template>
      </SettingsRow>
    </SettingsSection>

    <SettingsSection>
      <DefinitionList :items="readonlyItems" />
    </SettingsSection>

    <SettingsSection v-if="session.isOwner">
      <SettingsRow
        :label="t(user.data.value?.is_blocked ? 'admin.unblockUser' : 'admin.blockUser')"
        :hint="blocking ? t('app.working') : undefined"
        navigable
        :destructive="!user.data.value?.is_blocked"
        :busy="blocking"
        @click="onToggleBlock"
      />
    </SettingsSection>
  </StateBlock>
</template>
