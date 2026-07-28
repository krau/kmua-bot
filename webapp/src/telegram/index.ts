/**
 * Telegram SDK integration.
 *
 * Everything Telegram-specific is funnelled through this module so the rest of the
 * app never touches the SDK directly. That keeps components testable outside a
 * Telegram environment and gives one place to handle the version gate: each
 * component and method has its own minimum client version, so every call is
 * guarded with `isAvailable()` and degrades quietly on older clients.
 */

import {
  backButton,
  closingBehavior,
  hapticFeedback,
  init as initSdk,
  isTMA,
  mainButton,
  miniApp,
  popup,
  retrieveLaunchParams,
  retrieveRawInitData,
  secondaryButton,
  themeParams,
  viewport,
} from "@telegram-apps/sdk";

import * as mirrorState from "./button-mirror";

let ready = false;

export interface LaunchContext {
  initDataRaw: string;
  /** Chat id decoded from ?startapp=, used for navigation only. */
  startChatId: number | null;
}

/** Whether the page is running inside a Telegram client. */
export function insideTelegram(): boolean {
  try {
    return isTMA();
  } catch {
    return false;
  }
}

/**
 * Boot the SDK and bind the CSS variables the design tokens read.
 *
 * `bindCssVars` is what makes the panel follow the user's own client theme: it
 * writes --tg-theme-* onto the document, and `styles/main.css` maps those onto the
 * Tailwind colour tokens.
 */
export async function setupTelegram(): Promise<void> {
  if (ready) return;

  initSdk();

  if (themeParams.mountSync.isAvailable()) {
    themeParams.mountSync();
    // `bindCssVars` throws if the variables are already bound, and the SDK's state
    // outlives a module reload (HMR, or `vi.resetModules()` in tests). Checking
    // first keeps a second call harmless instead of aborting the whole boot.
    if (themeParams.bindCssVars.isAvailable() && !themeParams.isCssVarsBound()) {
      themeParams.bindCssVars();
    }
  }

  if (viewport.mount.isAvailable()) {
    await viewport.mount();
    if (viewport.bindCssVars.isAvailable() && !viewport.isCssVarsBound()) {
      viewport.bindCssVars();
    }
    // Full height from the start; a panel that opens half-height then jumps reads
    // as a glitch.
    if (viewport.expand.isAvailable()) viewport.expand();
  }

  if (backButton.mount.isAvailable()) backButton.mount();
  if (mainButton.mount.isAvailable()) mainButton.mount();
  if (secondaryButton.mount.isAvailable()) secondaryButton.mount();
  if (closingBehavior.mount.isAvailable()) closingBehavior.mount();

  if (miniApp.ready.isAvailable()) miniApp.ready();

  ready = true;
}

/**
 * Read the launch parameters this session authenticates with.
 *
 * The raw initData string is required, not the parsed object: Telegram's HMAC
 * covers exactly those bytes in that order, so any re-serialisation would break
 * verification.
 */
export function launchContext(): LaunchContext {
  return {
    initDataRaw: retrieveRawInitData() ?? "",
    startChatId: parseStartParam(retrieveLaunchParams().tgWebAppStartParam),
  };
}

function parseStartParam(value: string | undefined): number | null {
  if (!value || !value.startsWith("c")) return null;
  const digits = value.slice(1);
  if (!/^\d+$/.test(digits)) return null;
  return -Number(digits);
}

/**
 * True when the client reports a dark theme.
 *
 * Derived from the theme params Telegram sent, not from the OS preference: a user
 * on a light system with a dark Telegram must get the dark panel.
 */
export function isDarkTheme(): boolean {
  try {
    return Boolean(themeParams.isDark());
  } catch {
    return window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false;
  }
}

/** Subscribe to theme changes so the panel can follow a live switch. */
export function onThemeChange(handler: () => void): () => void {
  try {
    return themeParams.state.sub(handler);
  } catch {
    return () => {};
  }
}

export const haptics = {
  tap(): void {
    if (hapticFeedback.impactOccurred.isAvailable()) {
      hapticFeedback.impactOccurred("light");
    }
  },
  success(): void {
    if (hapticFeedback.notificationOccurred.isAvailable()) {
      hapticFeedback.notificationOccurred("success");
    }
  },
  warning(): void {
    if (hapticFeedback.notificationOccurred.isAvailable()) {
      hapticFeedback.notificationOccurred("warning");
    }
  },
  error(): void {
    if (hapticFeedback.notificationOccurred.isAvailable()) {
      hapticFeedback.notificationOccurred("error");
    }
  },
};

export interface ConfirmOptions {
  title: string;
  message: string;
  confirmText: string;
  destructive?: boolean;
}

/**
 * Ask for confirmation using Telegram's native dialog.
 *
 * Native rather than a hand-built modal: it is accessible, it matches the client,
 * and it cannot be dismissed by a stray tap on a backdrop. The cancel button uses
 * Telegram's own localised label, so it is always in the user's language. When the
 * API is unavailable it falls back to `window.confirm` rather than proceeding
 * silently - these are destructive actions.
 */
export async function confirm(options: ConfirmOptions): Promise<boolean> {
  if (options.destructive) haptics.warning();

  if (popup.show.isAvailable()) {
    const buttonId = await popup.show({
      // Telegram truncates hard: 64 chars for the title, 256 for the message.
      title: options.title.slice(0, 64),
      message: options.message.slice(0, 256),
      buttons: [
        {
          id: "confirm",
          type: options.destructive ? "destructive" : "default",
          text: options.confirmText.slice(0, 64),
        },
        { id: "cancel", type: "cancel" },
      ],
    });
    return buttonId === "confirm";
  }

  return window.confirm(`${options.title}\n\n${options.message}`);
}

export interface MainButtonState {
  text: string;
  visible: boolean;
  enabled: boolean;
  loading?: boolean;
}

/**
 * In a browser the client draws no buttons, so the requested state is mirrored into
 * refs that `DevBottomBar.vue` renders. `import.meta.env.DEV` is a compile-time
 * constant, so all of this disappears from a production build.
 */
function mirror(
  target: typeof mirrorState.mainButtonState | typeof mirrorState.secondaryButtonState,
  state: MainButtonState,
): void {
  if (!import.meta.env.DEV) return;
  target.value = {
    text: state.text,
    visible: state.visible,
    enabled: state.enabled,
    loading: state.loading ?? false,
  };
}

/** Drive the native main button, which is the panel's only save affordance. */
export const primaryButton = {
  set(state: MainButtonState): void {
    mirror(mirrorState.mainButtonState, state);
    if (!mainButton.setParams.isAvailable()) return;
    mainButton.setParams({
      text: state.text,
      isVisible: state.visible,
      isEnabled: state.enabled,
      isLoaderVisible: state.loading ?? false,
    });
  },
  hide(): void {
    mirror(mirrorState.mainButtonState, { text: "", visible: false, enabled: false });
    if (mainButton.setParams.isAvailable()) {
      mainButton.setParams({ isVisible: false, isEnabled: false, isLoaderVisible: false });
    }
  },
  onClick(handler: () => void): () => void {
    if (import.meta.env.DEV) mirrorState.mainButtonHandler.value = handler;
    if (!mainButton.onClick.isAvailable()) {
      return () => {
        if (import.meta.env.DEV) mirrorState.mainButtonHandler.value = null;
      };
    }
    const off = mainButton.onClick(handler);
    return () => {
      if (import.meta.env.DEV) mirrorState.mainButtonHandler.value = null;
      off();
    };
  },
};

/** The secondary button carries "discard changes". Requires client 7.10+. */
export const resetButton = {
  set(state: MainButtonState): void {
    mirror(mirrorState.secondaryButtonState, state);
    if (!secondaryButton.setParams.isAvailable()) return;
    secondaryButton.setParams({
      text: state.text,
      isVisible: state.visible,
      isEnabled: state.enabled,
    });
  },
  hide(): void {
    mirror(mirrorState.secondaryButtonState, { text: "", visible: false, enabled: false });
    if (secondaryButton.setParams.isAvailable()) {
      secondaryButton.setParams({ isVisible: false, isEnabled: false });
    }
  },
  onClick(handler: () => void): () => void {
    if (import.meta.env.DEV) mirrorState.secondaryButtonHandler.value = handler;
    if (!secondaryButton.onClick.isAvailable()) {
      return () => {
        if (import.meta.env.DEV) mirrorState.secondaryButtonHandler.value = null;
      };
    }
    const off = secondaryButton.onClick(handler);
    return () => {
      if (import.meta.env.DEV) mirrorState.secondaryButtonHandler.value = null;
      off();
    };
  },
};

/** Bind the native back button to a handler. */
export const navButton = {
  show(): void {
    if (import.meta.env.DEV) mirrorState.backButtonVisible.value = true;
    if (backButton.show.isAvailable()) backButton.show();
  },
  hide(): void {
    if (import.meta.env.DEV) mirrorState.backButtonVisible.value = false;
    if (backButton.hide.isAvailable()) backButton.hide();
  },
  onClick(handler: () => void): () => void {
    if (import.meta.env.DEV) mirrorState.backButtonHandler.value = handler;
    if (!backButton.onClick.isAvailable()) {
      return () => {
        if (import.meta.env.DEV) mirrorState.backButtonHandler.value = null;
      };
    }
    const off = backButton.onClick(handler);
    return () => {
      if (import.meta.env.DEV) mirrorState.backButtonHandler.value = null;
      off();
    };
  },
};

/** Warn before closing while edits are pending. */
export function setClosingConfirmation(enabled: boolean): void {
  if (enabled) {
    if (closingBehavior.enableConfirmation.isAvailable()) {
      closingBehavior.enableConfirmation();
    }
    return;
  }
  if (closingBehavior.disableConfirmation.isAvailable()) {
    closingBehavior.disableConfirmation();
  }
}
