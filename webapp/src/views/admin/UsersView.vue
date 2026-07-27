<script setup lang="ts">
/**
 * All users the bot knows about, searchable.
 *
 * `only_real` filters out bots and channel-sender pseudo-users, which otherwise pad
 * the list with rows nobody wants to edit.
 */
import { computed, ref, watch } from "vue";
import { useRouter } from "vue-router";

import { fetchUsers } from "@/api/endpoints/admin";
import PageHeader from "@/components/PageHeader.vue";
import PagerBar from "@/components/PagerBar.vue";
import SettingsRow from "@/components/SettingsRow.vue";
import SettingsSection from "@/components/SettingsSection.vue";
import StateBlock from "@/components/StateBlock.vue";
import TextField from "@/components/TextField.vue";
import ToggleSwitch from "@/components/ToggleSwitch.vue";
import { useAsyncData } from "@/composables/useAsyncData";
import { useDebouncedRef } from "@/composables/useDebouncedRef";
import { t } from "@/i18n";
import { formatNumber } from "@/utils/format";

const PAGE_SIZE = 20;

const router = useRouter();
const page = ref(1);
const search = ref("");
const onlyReal = ref(false);
const debouncedSearch = useDebouncedRef(search, 300);

const users = useAsyncData((signal) =>
  fetchUsers(page.value, PAGE_SIZE, debouncedSearch.value, onlyReal.value, signal),
);

watch(page, () => void users.reload());
watch([debouncedSearch, onlyReal], () => {
  if (page.value !== 1) {
    page.value = 1;
    return;
  }
  void users.reload();
});

const items = computed(() => users.data.value?.items ?? []);
const total = computed(() => users.data.value?.total ?? 0);

/** Role and status flags, shown as words rather than coloured pills. */
function badges(user: (typeof items.value)[number]): string {
  const flags: string[] = [];
  if (user.is_owner) flags.push(t("admin.isOwner"));
  if (user.is_bot_global_admin) flags.push(t("admin.globalAdmin"));
  if (user.is_bot) flags.push(t("admin.isBot"));
  else if (!user.is_real_user) flags.push(t("admin.notRealUser"));
  return flags.join(" · ");
}
</script>

<template>
  <PageHeader :title="t('admin.userList')" :subtitle="String(total)" />

  <SettingsSection>
    <TextField
      v-model="search"
      :label="t('app.search')"
      :placeholder="t('admin.searchUsers')"
      inputmode="search"
      :maxlength="128"
    />
    <SettingsRow :label="t('admin.onlyRealUsers')">
      <template #control>
        <ToggleSwitch v-model="onlyReal" :aria-label="t('admin.onlyRealUsers')" />
      </template>
    </SettingsRow>
  </SettingsSection>

  <StateBlock
    :loading="users.loading.value && !users.data.value"
    :error="users.error.value"
    :empty="!users.loading.value && items.length === 0"
    @retry="users.reload"
  >
    <SettingsSection>
      <SettingsRow
        v-for="user in items"
        :key="user.id"
        :label="user.full_name"
        :hint="badges(user) || (user.username ? `@${user.username}` : String(user.id))"
        :value="formatNumber(user.coins)"
        navigable
        @click="router.push({ name: 'admin-user', params: { userId: String(user.id) } })"
      />
    </SettingsSection>

    <PagerBar v-model:page="page" :size="PAGE_SIZE" :total="total" :loading="users.loading.value" />
  </StateBlock>
</template>
