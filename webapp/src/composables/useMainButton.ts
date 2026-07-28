/**
 * Declarative binding for Telegram's native main and secondary buttons.
 *
 * Saving lives on the client's own button rather than a floating button inside the
 * page: it sits where the user expects it in every other Mini App, it never covers
 * content, and it comes with a loading state. The trade-off is that it is global
 * state, so it must be released on unmount - which is what this composable exists
 * to guarantee.
 */

import { onScopeDispose, watchEffect, type Ref } from "vue";

import { primaryButton, resetButton } from "@/telegram";

export interface MainButtonOptions {
  text: Ref<string> | (() => string);
  visible: Ref<boolean> | (() => boolean);
  enabled: Ref<boolean> | (() => boolean);
  loading?: Ref<boolean> | (() => boolean);
  onClick: () => void;
  /** Optional secondary button, typically "discard changes". */
  secondary?: {
    text: Ref<string> | (() => string);
    visible: Ref<boolean> | (() => boolean);
    onClick: () => void;
  };
}

function read<T>(source: Ref<T> | (() => T)): T {
  return typeof source === "function" ? source() : source.value;
}

export function useMainButton(options: MainButtonOptions): void {
  const offPrimary = primaryButton.onClick(options.onClick);
  const offSecondary = options.secondary ? resetButton.onClick(options.secondary.onClick) : null;

  watchEffect(() => {
    primaryButton.set({
      text: read(options.text),
      visible: read(options.visible),
      enabled: read(options.enabled),
      loading: options.loading ? read(options.loading) : false,
    });
  });

  if (options.secondary) {
    const secondary = options.secondary;
    watchEffect(() => {
      resetButton.set({
        text: read(secondary.text),
        visible: read(secondary.visible),
        enabled: read(secondary.visible),
      });
    });
  }

  onScopeDispose(() => {
    offPrimary();
    offSecondary?.();
    primaryButton.hide();
    resetButton.hide();
  });
}
