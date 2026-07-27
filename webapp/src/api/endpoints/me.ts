import { api } from "../client";
import type { ChatBrief, Gift, Me, MeConfigPatch, Page, Quote, Waifu } from "../types";

export function fetchMe(signal?: AbortSignal) {
  return api.get<Me>("/api/me", signal ? { signal } : {});
}

export function updateMyConfig(patch: MeConfigPatch) {
  return api.patch<Me>("/api/me/config", patch);
}

export function fetchMyChats(signal?: AbortSignal) {
  return api.get<ChatBrief[]>("/api/me/chats", signal ? { signal } : {});
}

export function fetchMyQuotes(page: number, size: number, signal?: AbortSignal) {
  return api.get<Page<Quote>>("/api/me/quotes", {
    query: { page, size },
    ...(signal ? { signal } : {}),
  });
}

export function deleteMyQuote(link: string) {
  return api.delete<void>(`/api/me/quotes/${encodeURIComponent(link)}`);
}

export function fetchMyWaifu(signal?: AbortSignal) {
  return api.get<Waifu>("/api/me/waifu", signal ? { signal } : {});
}

export function divorce() {
  return api.post<Waifu>("/api/me/divorce");
}

export function fetchMyGifts(sent = false, signal?: AbortSignal) {
  return api.get<Gift[]>("/api/me/gifts", {
    query: { sent },
    ...(signal ? { signal } : {}),
  });
}

export function refreshMyAvatar() {
  return api.post<{ refreshed: boolean }>("/api/me/avatar/refresh");
}
