<script setup lang="ts">
/**
 * The caller's gift inventory.
 *
 * Read-only: gifts are bought and given in chat. Split into bag and given rather
 * than one list with a status pill, because the two groups mean different things and
 * grouping says so without decoration.
 */
import { computed } from "vue";

import { fetchMyGifts } from "@/api/endpoints/me";
import PageHeader from "@/components/PageHeader.vue";
import SettingsRow from "@/components/SettingsRow.vue";
import SettingsSection from "@/components/SettingsSection.vue";
import StateBlock from "@/components/StateBlock.vue";
import { useAsyncData } from "@/composables/useAsyncData";
import { t } from "@/i18n";
import { formatDate } from "@/utils/format";

// The endpoint filters on `sent`, so bag and given are two separate requests.
const bag = useAsyncData((signal) => fetchMyGifts(false, signal));
const given = useAsyncData((signal) => fetchMyGifts(true, signal));

const bagItems = computed(() => bag.data.value ?? []);
const givenItems = computed(() => given.data.value ?? []);

const loading = computed(
  () => (bag.loading.value && !bag.data.value) || (given.loading.value && !given.data.value),
);
const error = computed(() => bag.error.value ?? given.error.value);
const empty = computed(
  () => !loading.value && bagItems.value.length + givenItems.value.length === 0,
);

function reload(): void {
  void bag.reload();
  void given.reload();
}
</script>

<template>
  <PageHeader :title="t('gifts.title')" />

  <StateBlock :loading="loading" :error="error" :empty="empty" @retry="reload">
    <SettingsSection v-if="bagItems.length" :label="t('gifts.inBag')">
      <SettingsRow
        v-for="gift in bagItems"
        :key="gift.id"
        :label="gift.display_name"
        :hint="formatDate(gift.created_at)"
        :value="gift.rarity_name"
      />
    </SettingsSection>

    <SettingsSection v-if="givenItems.length" :label="t('gifts.sentToBot')">
      <SettingsRow
        v-for="gift in givenItems"
        :key="gift.id"
        :label="gift.display_name"
        :hint="formatDate(gift.created_at)"
        :value="gift.rarity_name"
      />
    </SettingsSection>
  </StateBlock>
</template>
