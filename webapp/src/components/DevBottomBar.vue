<script setup lang="ts">
/**
 * Stand-in for Telegram's native buttons, in a browser only.
 *
 * The main, secondary and back buttons are drawn by the Telegram client. In a plain
 * browser they simply do not exist, which would make saving unreachable and the whole
 * panel untestable outside Telegram.
 *
 * This mirrors the state the app requested and renders it at the bottom of the
 * viewport. It is styled to look like the real thing rather than to look nice: the
 * point is that what you see in the browser matches what a Telegram user gets.
 *
 * `import.meta.env.DEV` is a compile-time constant, so this component and its import
 * are removed from a production build.
 */
import { ChevronLeft } from "@lucide/vue";
import { t } from "@/i18n";
import {
  backButtonHandler,
  backButtonVisible,
  mainButtonHandler,
  mainButtonState,
  secondaryButtonHandler,
  secondaryButtonState,
} from "@/telegram/button-mirror";
</script>

<template>
  <div class="border-line bg-surface fixed inset-x-0 bottom-0 z-50 border-t" data-dev-bottom-bar>
    <p class="text-hint px-related pt-1 text-center text-note">浏览器预览 / Telegram 控件</p>

    <div class="flex items-center gap-tight p-tight">
      <button
        v-if="backButtonVisible"
        type="button"
        class="dev-bottom-bar__back"
        :aria-label="t('app.back')"
        @click="backButtonHandler?.()"
      >
        <ChevronLeft :size="18" :stroke-width="1.5" aria-hidden="true" />
      </button>

      <button
        v-if="secondaryButtonState.visible"
        type="button"
        class="border-line flex-1 border px-3 py-2 text-sub"
        :disabled="!secondaryButtonState.enabled"
        :class="secondaryButtonState.enabled ? '' : 'opacity-40'"
        @click="secondaryButtonHandler?.()"
      >
        {{ secondaryButtonState.text }}
      </button>

      <button
        v-if="mainButtonState.visible"
        type="button"
        class="bg-accent dark:bg-accent-dark flex-[2] px-3 py-2 text-sub text-white"
        :disabled="!mainButtonState.enabled"
        :class="mainButtonState.enabled ? '' : 'opacity-40'"
        @click="mainButtonHandler?.()"
      >
        {{ mainButtonState.loading ? "…" : mainButtonState.text }}
      </button>

      <span
        v-if="!mainButtonState.visible && !secondaryButtonState.visible"
        class="text-hint flex-1 px-2 py-2 text-center text-note"
      >
        无待保存更改
      </span>
    </div>
  </div>
</template>

<style scoped>
[data-dev-bottom-bar] {
  border-top-width: 0.5px;
  background: var(--kmua-surface);
}

[data-dev-bottom-bar] p {
  padding-block: 0.5rem 0;
  font-family: var(--font-sans);
}
[data-dev-bottom-bar] button {
  min-height: 2.5rem;
  border: 0;
  border-radius: 0.625rem;
  font-weight: 500;
}
[data-dev-bottom-bar] button.bg-accent {
  color: var(--kmua-bg);
}
.dev-bottom-bar__back {
  display: grid;
  width: 2.5rem;
  place-items: center;
  background: var(--kmua-accent-soft);
  color: var(--kmua-accent);
}
</style>
