/**
 * Boot sequence.
 *
 * Order matters: the SDK has to be initialised and the theme variables bound before
 * anything renders, or the first paint uses fallback colours and visibly corrects
 * itself. Authentication happens before mount too, so the app never renders a
 * signed-out state - inside Telegram there is no such thing.
 */

import { createApp } from "vue";
import { createPinia } from "pinia";

import App from "./App.vue";
import { router } from "./router";
import { isApiError } from "./api/errors";
import { t, tError } from "./i18n";
import { insideTelegram, isDarkTheme, setupTelegram } from "./telegram";
import { useSessionStore } from "./stores/session";
import { useMeStore } from "./stores/me";
import { applyContrastFallback } from "./utils/contrast";

import "./styles/main.css";

/**
 * Render a boot failure as plain text.
 *
 * If authentication fails there is no app to show a toast inside, and a blank
 * screen tells the user nothing. Kept dependency-free so it works even when the
 * failure happened before Vue mounted.
 */
function renderFatal(message: string): void {
  const root = document.getElementById("app");
  if (!root) return;
  root.textContent = "";

  const wrapper = document.createElement("div");
  wrapper.className = "app-shell";

  const text = document.createElement("p");
  text.className = "px-related text-body";
  text.textContent = message;

  wrapper.append(text);
  root.append(wrapper);
}

/**
 * Make a browser look enough like Telegram to run the panel.
 *
 * Only in a dev build, and only when `VITE_DEV_INIT_DATA` is present - see
 * `telegram/dev-mock.ts`. The payload it feeds in is genuinely signed with the bot
 * token, so the backend verifies it exactly as it would a real launch.
 */
async function tryDevEnvironment(): Promise<boolean> {
  if (!import.meta.env.DEV) return false;
  const { installDevTelegramEnv } = await import("./telegram/dev-mock");
  return installDevTelegramEnv();
}

async function boot(): Promise<void> {
  if (!insideTelegram() && !(await tryDevEnvironment())) {
    // A plain browser with no dev payload: there are no launch parameters to
    // verify, so there is nothing useful to show.
    document.documentElement.dataset.theme = "light";
    renderFatal(t("app.notInTelegram"));
    return;
  }

  await setupTelegram();
  document.documentElement.dataset.theme = isDarkTheme() ? "dark" : "light";
  applyContrastFallback();

  const app = createApp(App);
  app.use(createPinia());

  const session = useSessionStore();
  try {
    await session.signIn();
  } catch (error) {
    renderFatal(isApiError(error) ? tError(error.code) : t("errors.INIT_DATA_MISSING"));
    return;
  }

  // Loaded before mount so the very first render is already in the user's
  // language, rather than flashing the default and switching.
  const me = useMeStore();
  try {
    await me.load();
  } catch {
    // Non-fatal: the profile page will surface and retry this itself.
  }

  app.use(router);

  // A group deep link (?startapp=c<id>) opens straight on that group's page.
  const startChatId = session.takeStartChatId();
  if (startChatId !== null) {
    await router.replace({ name: "chat-config", params: { chatId: String(startChatId) } });
  }

  await router.isReady();
  app.mount("#app");
}

void boot();
