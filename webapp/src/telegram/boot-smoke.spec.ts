/**
 * Boot smoke test for the browser dev harness.
 *
 * `setupTelegram()` mounts the viewport, which asks the client for its dimensions and
 * waits for the reply. In a browser there is no client, so the mock has to answer -
 * and if it does not, this promise never settles and the app renders nothing. That is
 * a white screen with no error in the console, which is why it is worth a test.
 */

import { describe, expect, it, vi } from "vitest";

import { fakeInitData } from "./__fixtures__/launch-params";

const PAYLOAD = fakeInitData();

describe("dev boot", () => {
  it("completes SDK setup and hands the app its launch context", async () => {
    vi.resetModules();
    vi.stubEnv("VITE_DEV_INIT_DATA", PAYLOAD);

    const { installDevTelegramEnv } = await import("@/telegram/dev-mock");
    expect(installDevTelegramEnv()).toBe(true);

    const { isDarkTheme, launchContext, setupTelegram } = await import("@/telegram");

    // Fails by timing out rather than throwing if the mock stops answering the
    // viewport request.
    await setupTelegram();

    expect(launchContext().initDataRaw).toBe(PAYLOAD);
    expect(typeof isDarkTheme()).toBe("boolean");
  }, 15_000);

  it("decodes a group deep link into a chat id", async () => {
    vi.resetModules();
    vi.stubEnv("VITE_DEV_INIT_DATA", fakeInitData({ startParam: "c1852445173" }));

    const { installDevTelegramEnv } = await import("@/telegram/dev-mock");
    installDevTelegramEnv();

    const { launchContext, setupTelegram } = await import("@/telegram");
    await setupTelegram();

    expect(launchContext().startChatId).toBe(-1852445173);
  }, 15_000);
});
