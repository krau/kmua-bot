/**
 * HTTP client tests.
 *
 * The 401 path is the one that matters: it silently re-authenticates and replays the
 * request, and a bug there is either a user bounced out mid-edit or an infinite retry
 * loop against the auth endpoint.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api, setReauthenticator, setSessionToken } from "@/api/client";
import { ApiError } from "@/api/errors";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("api client", () => {
  beforeEach(() => {
    setSessionToken(null);
    setReauthenticator(null);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("sends the session token as a bearer header", async () => {
    setSessionToken("token-abc");
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ ok: true }));
    vi.stubGlobal("fetch", fetchMock);

    await api.get("/api/me");

    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer token-abc");
  });

  it("omits the body on a GET", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({}));
    vi.stubGlobal("fetch", fetchMock);

    await api.get("/api/me");

    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect(init.body).toBeUndefined();
    expect((init.headers as Record<string, string>)["Content-Type"]).toBeUndefined();
  });

  it("serialises the body and sets the content type on a write", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({}));
    vi.stubGlobal("fetch", fetchMock);

    await api.patch("/api/me/config", { lang: "en" });

    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect(init.body).toBe('{"lang":"en"}');
    expect((init.headers as Record<string, string>)["Content-Type"]).toBe("application/json");
  });

  it("drops empty query parameters", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({}));
    vi.stubGlobal("fetch", fetchMock);

    await api.get("/api/admin/users", { query: { page: 1, q: "", only_real: false } });

    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/admin/users?page=1&only_real=false");
  });

  it("returns undefined for a 204", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(api.delete("/api/me/quotes/x")).resolves.toBeUndefined();
  });

  it("throws an ApiError carrying the backend error code", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse({ code: "CHAT_NOT_FOUND", message: "nope" }, 404));
    vi.stubGlobal("fetch", fetchMock);

    await expect(api.get("/api/chats/-1")).rejects.toMatchObject({
      code: "CHAT_NOT_FOUND",
      status: 404,
    });
  });

  it("falls back to a generic code when the error body is not JSON", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response("<html>gateway timeout</html>", { status: 504 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(api.get("/api/me")).rejects.toBeInstanceOf(ApiError);
    await expect(api.get("/api/me")).rejects.toMatchObject({
      code: "INTERNAL_ERROR",
      status: 504,
    });
  });

  it("re-authenticates once on a 401 and replays the request", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ code: "TOKEN_EXPIRED" }, 401))
      .mockResolvedValueOnce(jsonResponse({ id: 1 }));
    vi.stubGlobal("fetch", fetchMock);

    const reauth = vi.fn().mockResolvedValue("fresh-token");
    setReauthenticator(reauth);

    await expect(api.get("/api/me")).resolves.toEqual({ id: 1 });

    expect(reauth).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const retryInit = fetchMock.mock.calls[1]?.[1] as RequestInit;
    expect((retryInit.headers as Record<string, string>).Authorization).toBe("Bearer fresh-token");
  });

  it("does not retry more than once, so a persistent 401 cannot loop", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ code: "TOKEN_INVALID" }, 401));
    vi.stubGlobal("fetch", fetchMock);

    const reauth = vi.fn().mockResolvedValue("still-bad");
    setReauthenticator(reauth);

    await expect(api.get("/api/me")).rejects.toMatchObject({ code: "TOKEN_INVALID" });

    expect(reauth).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("surfaces the 401 unchanged when no re-authenticator is registered", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ code: "TOKEN_MISSING" }, 401));
    vi.stubGlobal("fetch", fetchMock);

    await expect(api.get("/api/me")).rejects.toMatchObject({ code: "TOKEN_MISSING" });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
