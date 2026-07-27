/**
 * HTTP client for the panel API.
 *
 * Two decisions worth stating:
 *
 * - The session token is held in memory only. A Mini App re-authenticates from
 *   initData on every launch, which is cheap, so persisting it would add an
 *   attack surface (anything with DOM access could read it) for no benefit.
 * - A 401 triggers exactly one silent re-authentication and replay. A Mini App
 *   session can outlive a 6 hour token, and making the user close and reopen the
 *   app for that is poor; retrying more than once would risk a loop.
 */

import type { ApiErrorBody } from "./errors";
import { ApiError } from "./errors";

type Method = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

interface RequestOptions {
  method?: Method;
  body?: unknown;
  query?: Record<string, string | number | boolean | undefined>;
  signal?: AbortSignal;
  /** Internal: set while replaying a request after re-authentication. */
  isRetry?: boolean;
}

let sessionToken: string | null = null;
let reauthenticate: (() => Promise<string>) | null = null;

export function setSessionToken(token: string | null): void {
  sessionToken = token;
}

/**
 * Register how to obtain a fresh token. Provided by the session store, which owns
 * the Telegram SDK dependency; keeping it out of here leaves the client testable
 * without a Telegram environment.
 */
export function setReauthenticator(fn: (() => Promise<string>) | null): void {
  reauthenticate = fn;
}

function buildUrl(path: string, query?: RequestOptions["query"]): string {
  if (!query) return path;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === "") continue;
    params.set(key, String(value));
  }
  const qs = params.toString();
  return qs ? `${path}?${qs}` : path;
}

async function parseError(response: Response): Promise<ApiError> {
  // A failure response is not guaranteed to be JSON: a proxy timeout or an
  // unhandled 500 can return HTML, and that must not mask the real status.
  let body: ApiErrorBody | null;
  try {
    body = (await response.json()) as ApiErrorBody;
  } catch {
    body = null;
  }
  return new ApiError(
    body?.code ?? "INTERNAL_ERROR",
    body?.message ?? response.statusText,
    response.status,
    body?.details,
  );
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, query, signal, isRetry = false } = options;

  const headers: Record<string, string> = { Accept: "application/json" };
  if (sessionToken) headers.Authorization = `Bearer ${sessionToken}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";

  const init: RequestInit = { method, headers };
  if (body !== undefined) init.body = JSON.stringify(body);
  if (signal) init.signal = signal;

  const response = await fetch(buildUrl(path, query), init);

  if (response.status === 401 && !isRetry && reauthenticate) {
    const token = await reauthenticate();
    sessionToken = token;
    return request<T>(path, { ...options, isRetry: true });
  }

  if (!response.ok) {
    throw await parseError(response);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

export const api = {
  get: <T>(path: string, options?: Omit<RequestOptions, "method" | "body">) =>
    request<T>(path, { ...options, method: "GET" }),
  post: <T>(path: string, body?: unknown, options?: Omit<RequestOptions, "method" | "body">) =>
    request<T>(path, { ...options, method: "POST", body }),
  put: <T>(path: string, body?: unknown, options?: Omit<RequestOptions, "method" | "body">) =>
    request<T>(path, { ...options, method: "PUT", body }),
  patch: <T>(path: string, body?: unknown, options?: Omit<RequestOptions, "method" | "body">) =>
    request<T>(path, { ...options, method: "PATCH", body }),
  delete: <T>(path: string, options?: Omit<RequestOptions, "method" | "body">) =>
    request<T>(path, { ...options, method: "DELETE" }),
};
