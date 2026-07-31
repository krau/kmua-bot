import { api } from "../client";
import type {
  ChatBrief,
  Gift,
  GiftCatalogItem,
  GiftUseResult,
  Me,
  MeConfigPatch,
  Page,
  Quote,
  RssSubscription,
  Waifu,
} from "../types";

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

export function fetchGiftCatalog(signal?: AbortSignal) {
  return api.get<GiftCatalogItem[]>("/api/me/gifts/catalog", signal ? { signal } : {});
}

export function buyGift(giftId: string) {
  return api.post<Gift>("/api/me/gifts/buy", { gift_id: giftId });
}

export function sendGift(giftDbId: number) {
  return api.post<GiftUseResult>(`/api/me/gifts/${giftDbId}/send`);
}

export function refreshMyAvatar() {
  return api.post<{ refreshed: boolean }>("/api/me/avatar/refresh");
}

export function fetchMyRss(page: number, size: number, signal?: AbortSignal) {
  return api.get<Page<RssSubscription>>("/api/me/rss", {
    query: { page, size },
    ...(signal ? { signal } : {}),
  });
}

export function addMyRss(url: string) {
  return api.post<RssSubscription>("/api/me/rss", { url });
}

export function setMyRssPaused(feedId: number, paused: boolean) {
  return api.patch<RssSubscription[]>(`/api/me/rss/${feedId}`, { paused });
}

export function setMyRssInterval(feedId: number, minutes: number | null) {
  return api.patch<RssSubscription[]>(`/api/me/rss/${feedId}`, { interval_minutes: minutes });
}

export function deleteMyRss(feedId: number) {
  return api.delete<void>(`/api/me/rss/${feedId}`);
}
