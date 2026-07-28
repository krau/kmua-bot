<script setup lang="ts">
/**
 * The caller's gift inventory.
 *
 * The private-chat gift loop belongs here too: the catalog makes prices and effects
 * inspectable, while the bag lets a user use a gift without remembering bot commands.
 */
import { computed, ref } from "vue";

import { buyGift, fetchGiftCatalog, fetchMyGifts, sendGift } from "@/api/endpoints/me";
import { isApiError } from "@/api/errors";
import PageHeader from "@/components/PageHeader.vue";
import SettingsRow from "@/components/SettingsRow.vue";
import SettingsSection from "@/components/SettingsSection.vue";
import StateBlock from "@/components/StateBlock.vue";
import { useAsyncData } from "@/composables/useAsyncData";
import { useNotice } from "@/composables/useNotice";
import { t } from "@/i18n";
import { useMeStore } from "@/stores/me";
import { confirm, haptics } from "@/telegram";
import { formatDate } from "@/utils/format";

// The endpoint filters on `sent`, so bag and given are two separate requests.
const bag = useAsyncData((signal) => fetchMyGifts(false, signal));
const given = useAsyncData((signal) => fetchMyGifts(true, signal));
const catalog = useAsyncData((signal) => fetchGiftCatalog(signal));
const meStore = useMeStore();
const { notify, notifyError } = useNotice();
const busyId = ref<string | number | null>(null);
const lastEffect = ref<string | null>(null);

const bagItems = computed(() => bag.data.value ?? []);
const givenItems = computed(() => given.data.value ?? []);

const loading = computed(
  () => (bag.loading.value && !bag.data.value) || (given.loading.value && !given.data.value),
);
const error = computed(() => bag.error.value ?? given.error.value);
async function buy(giftId: string, name: string, price: number): Promise<void> {
  if (
    !(await confirm({
      title: t("gifts.buy"),
      message: t("gifts.buyConfirm", { name, price }),
      confirmText: t("gifts.buy"),
    }))
  )
    return;
  busyId.value = giftId;
  try {
    const item = await buyGift(giftId);
    await Promise.all([bag.reload(), meStore.load(true)]);
    notify(t("gifts.bought", { rarity: item.rarity_name, name: item.display_name }));
    haptics.success();
  } catch (error) {
    notifyError(isApiError(error) ? t(`errors.${error.code}`) : t("app.loadFailed"));
    haptics.error();
  } finally {
    busyId.value = null;
  }
}

async function send(id: number, name: string): Promise<void> {
  if (
    !(await confirm({
      title: t("gifts.send"),
      message: t("gifts.sendConfirm", { name }),
      confirmText: t("gifts.send"),
      destructive: true,
    }))
  )
    return;
  busyId.value = id;
  try {
    const result = await sendGift(id);
    await Promise.all([bag.reload(), given.reload(), meStore.load(true)]);
    lastEffect.value = result.detail;
    notify(t("gifts.sent", { rarity: result.gift.rarity_name, name: result.gift.display_name }));
    haptics.success();
  } catch (error) {
    notifyError(isApiError(error) ? t(`errors.${error.code}`) : t("app.loadFailed"));
    haptics.error();
  } finally {
    busyId.value = null;
  }
}

function reload(): void {
  void bag.reload();
  void given.reload();
  void catalog.reload();
}
</script>

<template>
  <PageHeader :title="t('gifts.title')" />

  <StateBlock
    :loading="loading || catalog.loading.value"
    :error="error ?? catalog.error.value"
    @retry="reload"
  >
    <SettingsSection :label="t('gifts.shop')" :hint="t('gifts.shopHint')">
      <SettingsRow
        v-for="item in catalog.data.value ?? []"
        :key="item.gift_id"
        :label="item.display_name"
        :hint="`${item.description}\n${t('gifts.effect', { comment: item.comment })}`"
        :value="item.price"
        :busy="busyId === item.gift_id"
        navigable
        @click="buy(item.gift_id, item.display_name, item.price)"
      />
    </SettingsSection>

    <SettingsSection v-if="lastEffect" :label="t('gifts.lastEffect')">
      <p class="bg-surface rounded-container whitespace-pre-wrap px-related py-related text-sub">
        {{ lastEffect }}
      </p>
    </SettingsSection>

    <SettingsSection v-if="bagItems.length" :label="t('gifts.inBag')">
      <SettingsRow
        v-for="gift in bagItems"
        :key="gift.id"
        :label="gift.display_name"
        :hint="formatDate(gift.created_at)"
        :value="gift.rarity_name"
        :busy="busyId === gift.id"
        navigable
        @click="send(gift.id, gift.display_name)"
      />
    </SettingsSection>

    <SettingsSection v-else :label="t('gifts.inBag')">
      <SettingsRow :label="t('gifts.noInventory')" />
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

    <SettingsSection v-else :label="t('gifts.sentToBot')">
      <SettingsRow :label="t('gifts.noHistory')" />
    </SettingsSection>
  </StateBlock>
</template>
