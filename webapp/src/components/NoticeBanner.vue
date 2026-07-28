<script setup lang="ts">
/**
 * Transient feedback, as a thin bar at the top of the viewport.
 *
 * Fixed rather than in the document flow: it has to be visible when the page is
 * scrolled down (a save is confirmed by the native button at the bottom, so the user
 * is usually nowhere near the top), and anything inserted into the flow shifts the
 * content under it - a visible jolt every time something is saved.
 *
 * Translucent with a blur so it reads as an overlay on the page rather than a second
 * header competing with the title. The surface is Telegram's own header colour, so it
 * belongs to the client chrome above it.
 *
 * Only the two properties that change are transitioned, and only the bar moves - the
 * page underneath is untouched. `aria-live="polite"` announces the text without
 * stealing focus, which is the point of a notice as opposed to a dialog.
 *
 * Two details exist specifically to survive notices arriving back to back, e.g. two
 * saves in quick succession:
 *
 * 1. The bar carries no `:key`. With one, replacing a notice tore down one element and
 *    built another, and Vue's default transition runs both at once - so for 200ms two
 *    bars were in the DOM, stacked, shoving each other around. Without it Vue patches
 *    the text in place and the transition only plays on the true appear and disappear.
 * 2. The bar is absolutely positioned inside the region. Even if something does put two
 *    bars on screen at once, they overlay instead of queueing in the flow.
 */
import { useNotice } from "@/composables/useNotice";
import { haptics } from "@/telegram";

const { notice, dismiss } = useNotice();

function onDismiss(): void {
  haptics.tap();
  dismiss();
}
</script>

<template>
  <!--
    The live region is always mounted, and only its contents change: a region added to
    the DOM at the same moment as its text is unreliably announced by screen readers.
  -->
  <div class="notice-region" role="status" aria-live="polite" aria-atomic="true">
    <!--
      No `:key` here on purpose. Keying by notice id makes a replacement a
      remove-plus-insert, and both transitions run together: two bars on screen,
      overlapping and displacing each other. Unkeyed, a replacement is a text patch on
      the element already in place.
    -->
    <Transition name="notice">
      <button
        v-if="notice"
        type="button"
        class="notice-bar"
        :class="notice.kind === 'error' ? 'notice-bar--error' : 'notice-bar--success'"
        @click="onDismiss"
      >
        {{ notice.text }}
      </button>
    </Transition>
  </div>
</template>

<style scoped>
.notice-region {
  position: fixed;
  /* Below Telegram's own header, above everything of ours. */
  top: 0;
  left: 0;
  right: 0;
  z-index: 50;
  /*
    Zero height: the region is only an anchor and a live region, never a box. With a
    height it would reserve space at the top of every page for a bar that is usually
    not there. The safe-area inset is applied to the bar instead.
  */
  height: 0;
  /* The region spans the viewport but must not swallow taps where there is no bar. */
  pointer-events: none;
}

.notice-bar {
  pointer-events: auto;
  /*
    Taken out of the flow so a second bar can never be laid out beneath the first.
    The region has no height of its own, which is what makes that safe.
  */
  position: absolute;
  top: var(--tg-safe-area-inset-top, 0px);
  left: 0;
  right: 0;
  display: block;
  padding: 0.5rem var(--spacing-related);
  padding-left: calc(var(--spacing-related) + var(--tg-safe-area-inset-left, 0px));
  padding-right: calc(var(--spacing-related) + var(--tg-safe-area-inset-right, 0px));
  font-size: var(--text-sub);
  line-height: var(--text-sub--line-height);
  text-align: center;
  /*
    Translucent over the client's header colour. `color-mix` keeps it theme-driven:
    a hardcoded rgba() would be wrong in one of the two themes, and usually both.
  */
  background-color: color-mix(in srgb, var(--color-header) 82%, transparent);
  -webkit-backdrop-filter: blur(12px);
  backdrop-filter: blur(12px);
  /* Separation is a hairline, as everywhere else - no shadow. */
  border-bottom: 1px solid color-mix(in srgb, var(--color-line) 60%, transparent);
  /*
    A replacement patches this element rather than swapping it, so a success followed
    by a failure changes colour on the spot. Easing it keeps that from reading as a
    flicker.
  */
  transition: color 150ms ease-out;
}

/*
  Success speaks in the ink colour: a save that worked is not an event that needs a
  colour. Only the failure case is coloured, because there the colour is the message.
*/
.notice-bar--success {
  color: var(--color-ink);
}

.notice-bar--error {
  color: var(--color-danger);
}

:global([data-theme="dark"]) .notice-bar--error {
  color: var(--color-danger-dark);
}

/* Fade with a short slide from under the header; no bounce, no scale. */
.notice-enter-active,
.notice-leave-active {
  transition:
    opacity 200ms ease-out,
    translate 200ms ease-out;
}

.notice-enter-from,
.notice-leave-to {
  opacity: 0;
  translate: 0 -100%;
}
</style>
