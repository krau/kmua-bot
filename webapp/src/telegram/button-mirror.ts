/**
 * Mirror of the native button state, for the browser dev harness.
 *
 * The main, secondary and back buttons are drawn by the Telegram client, not by the
 * page - so in a plain browser they are invisible and there is no way to trigger a
 * save. This module records what the app asked for, and `DevBottomBar.vue` renders
 * it. In production nothing reads these refs.
 *
 * Kept as plain refs updated from the setters rather than a store, so the wrappers
 * in `telegram/index.ts` stay side-effect-only from the app's point of view.
 */

import { ref, shallowRef } from "vue";

export interface MirroredButton {
  text: string;
  visible: boolean;
  enabled: boolean;
  loading: boolean;
}

const EMPTY: MirroredButton = { text: "", visible: false, enabled: false, loading: false };

export const mainButtonState = ref<MirroredButton>({ ...EMPTY });
export const secondaryButtonState = ref<MirroredButton>({ ...EMPTY });
export const backButtonVisible = ref(false);

// shallowRef: these hold functions, which must not be made reactive.
export const mainButtonHandler = shallowRef<(() => void) | null>(null);
export const secondaryButtonHandler = shallowRef<(() => void) | null>(null);
export const backButtonHandler = shallowRef<(() => void) | null>(null);
