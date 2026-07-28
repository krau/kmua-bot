<script setup lang="ts">
/**
 * Home.
 *
 * Three entries at most, gated by role. Not a grid of icon tiles: each entry is a
 * row with a name and one line saying what is behind it, which is more useful than
 * a glyph somebody had to invent for "developer panel".
 */
import { computed } from "vue";
import { useRouter } from "vue-router";

import PageHeader from "@/components/PageHeader.vue";
import SettingsRow from "@/components/SettingsRow.vue";
import SettingsSection from "@/components/SettingsSection.vue";
import { t } from "@/i18n";
import { useMeStore } from "@/stores/me";
import { useSessionStore } from "@/stores/session";

const router = useRouter();
const session = useSessionStore();
const meStore = useMeStore();

const greeting = computed(() => session.user?.full_name ?? t("home.subtitle"));
const chatCount = computed(() => meStore.me?.chat_count ?? null);

function open(name: string): void {
  void router.push({ name });
}
</script>

<template>
  <PageHeader :title="t('home.title')" :subtitle="greeting" />

  <SettingsSection>
    <SettingsRow :label="t('home.me')" :hint="t('home.meHint')" navigable @click="open('me')" />
    <SettingsRow
      :label="t('home.chats')"
      :hint="t('home.chatsHint')"
      :value="chatCount"
      navigable
      @click="open('chats')"
    />
  </SettingsSection>

  <SettingsSection v-if="session.isBotAdmin">
    <SettingsRow
      :label="t('home.admin')"
      :hint="t('home.adminHint')"
      navigable
      @click="open('admin')"
    />
  </SettingsSection>
</template>
