<script setup lang="ts">
/**
 * App shell.
 *
 * Owns the two things that are global rather than per-page: the native back button
 * binding, and the theme flag that the dark variant and the contrast fallback read.
 */
// Aliased: `RouterView`'s slot also binds a `Component`, and the template scope
// would shadow this import.
import {
  defineAsyncComponent,
  onMounted,
  onUnmounted,
  shallowRef,
  type Component as VueComponent,
} from "vue";

import NoticeBanner from "@/components/NoticeBanner.vue";
import { useBackButton } from "@/composables/useBackButton";
import { useNoticeCleanup } from "@/composables/useNotice";
import { isDarkTheme, onThemeChange } from "@/telegram";
import { applyContrastFallback } from "@/utils/contrast";

/**
 * The browser stand-in for Telegram's native buttons.
 *
 * Loaded through a dynamic import inside an `import.meta.env.DEV` branch, not a plain
 * top-level import: Vite replaces that flag with `false` at build time, so the whole
 * branch and the module it references are dropped. A static import would keep the
 * component in the production bundle even though it never renders - which it did,
 * until this was changed.
 */
const devBottomBar = shallowRef<VueComponent | null>(null);
if (import.meta.env.DEV) {
  devBottomBar.value = defineAsyncComponent(() => import("@/components/DevBottomBar.vue"));
}

useBackButton();
// Notice state is module-scoped so it survives route changes; this drops whatever is
// pending if the shell itself goes away.
useNoticeCleanup();

function syncTheme(): void {
  document.documentElement.dataset.theme = isDarkTheme() ? "dark" : "light";
  applyContrastFallback();
}

let stopThemeWatch: (() => void) | null = null;

onMounted(() => {
  syncTheme();
  // Telegram can switch theme while the app is open; follow it live rather than
  // waiting for a reopen.
  stopThemeWatch = onThemeChange(syncTheme);
});

onUnmounted(() => stopThemeWatch?.());
</script>

<template>
  <!-- Mounted once, outside the shell: it is fixed to the viewport, not to a page. -->
  <NoticeBanner />

  <div class="app-shell">
    <RouterView v-slot="{ Component }">
      <component :is="Component" />
    </RouterView>
  </div>

  <component :is="devBottomBar" v-if="devBottomBar" />
</template>
