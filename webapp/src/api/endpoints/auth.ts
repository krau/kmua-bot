import { api } from "../client";
import type { AuthResponse, SystemInfo } from "../types";

export function authenticate(initDataRaw: string, signal?: AbortSignal) {
  return api.post<AuthResponse>(
    "/api/auth/telegram",
    { init_data_raw: initDataRaw },
    signal ? { signal } : {},
  );
}

export function systemInfo(signal?: AbortSignal) {
  return api.get<SystemInfo>("/api/system/info", signal ? { signal } : {});
}
