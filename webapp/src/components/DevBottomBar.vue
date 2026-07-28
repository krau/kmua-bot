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
    <p class="text-hint px-related pt-1 text-center font-mono text-[11px]">
      dev · Telegram 原生按钮模拟
    </p>

    <div class="flex items-center gap-tight p-tight">
      <button
        v-if="backButtonVisible"
        type="button"
        class="border-line shrink-0 border px-3 py-2 text-sub"
        @click="backButtonHandler?.()"
      >
        ‹
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
