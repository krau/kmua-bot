/**
 * Dev environment mock tests.
 *
 * The mock feeds a payload into the SDK, and the SDK validates it against its own
 * launch-params schema before the app ever sees it. That schema requires fields the
 * HMAC does not cover - `signature` in particular - so a payload the backend happily
 * verifies can still be rejected on the client, which shows up as a white screen.
 *
 * These tests catch that: they run the real mock against the real SDK and assert the
 * app can read back what it needs.
 *
 * The payload is synthetic (see `__fixtures__/launch-params.ts`). The SDK never checks
 * the signature, so a real one would add nothing here except a credential in the repo.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";

import { FAKE_USER_ID, fakeInitData } from "./__fixtures__/launch-params";

const PAYLOAD = fakeInitData();

async function loadWithEnv(initData: string | undefined) {
  vi.resetModules();
  vi.stubEnv("VITE_DEV_INIT_DATA", initData as string);
  return import("./dev-mock");
}

describe("installDevTelegramEnv", () => {
  beforeEach(() => {
    vi.unstubAllEnvs();
    window.history.replaceState({}, "", "/");
  });

  it("does nothing when no dev payload is configured", async () => {
    const { installDevTelegramEnv } = await loadWithEnv(undefined);

    expect(installDevTelegramEnv()).toBe(false);
  });

  it("installs an environment the SDK accepts", async () => {
    const { installDevTelegramEnv } = await loadWithEnv(PAYLOAD);

    expect(installDevTelegramEnv()).toBe(true);

    // The real failure mode this guards against: the SDK throws
    // InvalidLaunchParamsError here if a schema-required field is missing, and the
    // app renders nothing at all.
    const { retrieveLaunchParams, retrieveRawInitData } = await import("@telegram-apps/sdk");
    expect(() => retrieveLaunchParams()).not.toThrow();
    expect(retrieveRawInitData()).toBe(PAYLOAD);
  });

  it("exposes the payload byte-for-byte, so the backend HMAC still matches", async () => {
    const { installDevTelegramEnv } = await loadWithEnv(PAYLOAD);
    installDevTelegramEnv();

    const { retrieveRawInitData } = await import("@telegram-apps/sdk");

    // Any re-encoding would invalidate the signature the backend recomputes.
    expect(retrieveRawInitData()).toBe(PAYLOAD);
  });

  it("passes the user through to the app", async () => {
    const { installDevTelegramEnv } = await loadWithEnv(PAYLOAD);
    installDevTelegramEnv();

    const { retrieveLaunchParams } = await import("@telegram-apps/sdk");

    expect(retrieveLaunchParams().tgWebAppData?.user?.id).toBe(FAKE_USER_ID);
  });

  it("reports the platform and theme the app needs to boot", async () => {
    const { installDevTelegramEnv } = await loadWithEnv(PAYLOAD);
    installDevTelegramEnv();

    const { retrieveLaunchParams } = await import("@telegram-apps/sdk");
    const params = retrieveLaunchParams();

    expect(params.tgWebAppPlatform).toBe("tdesktop");
    // Launch params keep Telegram's snake_case keys; only the mounted themeParams
    // component camel-cases them.
    expect(params.tgWebAppThemeParams.bg_color).toBe("#ffffff");
  });

  it("uses the dark palette when ?theme=dark is present", async () => {
    window.history.replaceState({}, "", "/?theme=dark");
    const { installDevTelegramEnv } = await loadWithEnv(PAYLOAD);
    installDevTelegramEnv();

    const { retrieveLaunchParams } = await import("@telegram-apps/sdk");
    const theme = retrieveLaunchParams().tgWebAppThemeParams;

    expect(theme.bg_color).toBe("#17212b");
  });

  it("carries a start_param through, so group deep links work", async () => {
    const { installDevTelegramEnv } = await loadWithEnv(
      fakeInitData({ startParam: "c1852445173" }),
    );
    installDevTelegramEnv();

    const { retrieveRawInitData } = await import("@telegram-apps/sdk");

    expect(retrieveRawInitData()).toContain("start_param=c1852445173");
  });
});
