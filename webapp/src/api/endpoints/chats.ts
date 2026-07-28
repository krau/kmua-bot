import { api } from "../client";
import type {
  ChatAdmin,
  ChatConfig,
  ChatConfigInput,
  ChatDetail,
  Page,
  Quote,
  SyncMembersResult,
} from "../types";

export function fetchChat(chatId: number, signal?: AbortSignal) {
  return api.get<ChatDetail>(`/api/chats/${chatId}`, signal ? { signal } : {});
}

export function saveChatConfig(chatId: number, config: ChatConfigInput) {
  return api.put<ChatConfig>(`/api/chats/${chatId}/config`, config);
}

export function saveTitlePermissions(chatId: number, permissions: Record<string, boolean>) {
  return api.put<ChatConfig>(`/api/chats/${chatId}/title-permissions`, { permissions });
}

export function fetchChatAdmins(chatId: number, signal?: AbortSignal) {
  return api.get<ChatAdmin[]>(`/api/chats/${chatId}/admins`, signal ? { signal } : {});
}

export function promoteChatAdmin(chatId: number, userId: number) {
  return api.post<ChatAdmin[]>(`/api/chats/${chatId}/admins`, { user_id: userId });
}

export function demoteChatAdmin(chatId: number, userId: number) {
  return api.delete<ChatAdmin[]>(`/api/chats/${chatId}/admins/${userId}`);
}

export function syncChatMembers(chatId: number) {
  return api.post<SyncMembersResult>(`/api/chats/${chatId}/sync-members`);
}

export function fetchChatQuotes(
  chatId: number,
  page: number,
  size: number,
  q: string,
  signal?: AbortSignal,
) {
  return api.get<Page<Quote>>(`/api/chats/${chatId}/quotes`, {
    query: { page, size, q },
    ...(signal ? { signal } : {}),
  });
}

export function deleteChatQuote(chatId: number, link: string) {
  return api.delete<void>(`/api/chats/${chatId}/quotes/${encodeURIComponent(link)}`);
}
