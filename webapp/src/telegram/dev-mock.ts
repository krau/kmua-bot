/**
 * Telegram environment mock, for browser development only.
 *
 * The panel normally gets its launch parameters from a Telegram client. Outside
 * Telegram there is no client, and the backend will not relax its signature check
 * for a dev build - so instead `scripts/dev_init_data.py` produces a genuinely
 * signed payload using the bot token, and this module feeds it to the SDK.
 *
 * Two guards keep this out of production:
 *
 * - the whole module is only imported under `import.meta.env.DEV`, so a production
 *   build tree-shakes it away entirely;
 * - it does nothing unless `VITE_DEV_INIT_DATA` is set, which only ever lives in
 *   the gitignored `webapp/.env.local`.
 */

import { emitEvent, mockTelegramEnv } from "@telegram-apps/sdk";

/** Theme colours matching Telegram Desktop's default light theme. */
const LIGHT_THEME = {
  accent_text_color: "#168acd",
  bg_color: "#ffffff",
  bottom_bar_bg_color: "#f7f7f7",
  button_color: "#40a7e3",
  button_text_color: "#ffffff",
  destructive_text_color: "#d14e4e",
  header_bg_color: "#ffffff",
  hint_color: "#999999",
  link_color: "#168acd",
  secondary_bg_color: "#f1f1f1",
  section_bg_color: "#ffffff",
  section_header_text_color: "#168acd",
  section_separator_color: "#e7e7e7",
  subtitle_text_color: "#999999",
  text_color: "#000000",
} as const;

const DARK_THEME = {
  accent_text_color: "#6ab2f2",
  bg_color: "#17212b",
  bottom_bar_bg_color: "#17212b",
  button_color: "#5288c1",
  button_text_color: "#ffffff",
  destructive_text_color: "#ec3942",
  header_bg_color: "#17212b",
  hint_color: "#708499",
  link_color: "#6ab3f3",
  secondary_bg_color: "#232e3c",
  section_bg_color: "#17212b",
  section_header_text_color: "#6ab3f3",
  section_separator_color: "#111921",
  subtitle_text_color: "#708499",
  text_color: "#f5f5f5",
} as const;

/** A desktop browser has no notch or gesture bar. */
const ZERO_INSETS = { top: 0, bottom: 0, left: 0, right: 0 } as const;

/**
 * Install the mock. Returns false when no dev initData is configured, so the
 * caller can show the "open inside Telegram" message instead of a broken app.
 */
export function installDevTelegramEnv(): boolean {
  const initDataRaw = import.meta.env.VITE_DEV_INIT_DATA;
  if (!initDataRaw) return false;

  // ?theme=dark to check the dark palette without changing anything else.
  const params = new URLSearchParams(window.location.search);
  const dark = params.get("theme") === "dark";

  // Telegram surfaces `?startapp=` twice: as `start_param` inside the signed
  // initData, and as the separate `tgWebAppStartParam` launch parameter that
  // `launchContext()` reads. The generator can only put it in the signed half, so
  // it is lifted out here to keep both halves consistent.
  const startParam = new URLSearchParams(initDataRaw).get("start_param");

  mockTelegramEnv({
    launchParams: {
      tgWebAppData: initDataRaw,
      tgWebAppVersion: "8.0",
      tgWebAppPlatform: "tdesktop",
      tgWebAppThemeParams: dark ? DARK_THEME : LIGHT_THEME,
      ...(startParam ? { tgWebAppStartParam: startParam } : {}),
    },
    // The SDK posts method calls to a client that is not there. Requests that
    // expect a reply must be answered, or `viewport.mount()` never resolves and
    // the app hangs before it renders.
    onEvent([method, payload]) {
      switch (method) {
        case "web_app_request_viewport":
          emitEvent("viewport_changed", {
            height: window.innerHeight,
            width: window.innerWidth,
            is_state_stable: true,
            is_expanded: true,
          });
          return;
        case "web_app_request_safe_area":
          emitEvent("safe_area_changed", ZERO_INSETS);
          return;
        case "web_app_request_content_safe_area":
          emitEvent("content_safe_area_changed", ZERO_INSETS);
          return;
        case "web_app_request_theme":
          emitEvent("theme_changed", { theme_params: dark ? DARK_THEME : LIGHT_THEME });
          return;
        default:
          // eslint-disable-next-line no-console
          console.debug("[tg-mock]", method, payload ?? "");
      }
    },
  });

  // eslint-disable-next-line no-console
  console.info(
    `[tg-mock] Telegram environment mocked (${dark ? "dark" : "light"} theme). ` +
      "Append ?theme=dark to switch.",
  );
  return true;
}
