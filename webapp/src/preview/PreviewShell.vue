<script setup lang="ts">
import DevBottomBar from "@/components/DevBottomBar.vue";
import NoticeBanner from "@/components/NoticeBanner.vue";
import RouteTransition from "@/components/RouteTransition.vue";
import { useBackButton } from "@/composables/useBackButton";
import { useNoticeCleanup } from "@/composables/useNotice";

useBackButton();
useNoticeCleanup();
</script>

<template>
  <NoticeBanner />
  <div class="app-shell"><RouteTransition /></div>
  <DevBottomBar />
</template>
