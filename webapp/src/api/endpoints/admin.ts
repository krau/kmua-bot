import { api } from "../client";
import type {
  AdminChat,
  AdminUser,
  AdminUserPatch,
  AdminUserPatchResult,
  ChatDetail,
  ChatPolicyList,
  ChatPolicyPatch,
  ConfigReloadResult,
  ConfigSnapshot,
  Job,
  Page,
  Stats,
} from "../types";

export function fetchStats(signal?: AbortSignal) {
  return api.get<Stats>("/api/admin/stats", signal ? { signal } : {});
}

export function fetchConfig(signal?: AbortSignal) {
  return api.get<ConfigSnapshot>("/api/admin/config", signal ? { signal } : {});
}

export function reloadConfig() {
  return api.post<ConfigReloadResult>("/api/admin/config/reload");
}

export function fetchChats(page: number, size: number, q: string, signal?: AbortSignal) {
  return api.get<Page<AdminChat>>("/api/admin/chats", {
    query: { page, size, q },
    ...(signal ? { signal } : {}),
  });
}

export function fetchChat(chatId: number, signal?: AbortSignal) {
  return api.get<ChatDetail>(`/api/admin/chats/${chatId}`, signal ? { signal } : {});
}

export function leaveChat(chatId: number) {
  return api.post<{ left: boolean; purged: boolean }>(`/api/admin/chats/${chatId}/leave`);
}

export function fetchUsers(
  page: number,
  size: number,
  q: string,
  onlyReal: boolean,
  signal?: AbortSignal,
) {
  return api.get<Page<AdminUser>>("/api/admin/users", {
    query: { page, size, q, only_real: onlyReal },
    ...(signal ? { signal } : {}),
  });
}

export function fetchUser(userId: number, signal?: AbortSignal) {
  return api.get<AdminUser>(`/api/admin/users/${userId}`, signal ? { signal } : {});
}

export function updateUser(userId: number, patch: AdminUserPatch) {
  return api.patch<AdminUserPatchResult>(`/api/admin/users/${userId}`, patch);
}

export function fetchJobs(signal?: AbortSignal) {
  return api.get<Job[]>("/api/admin/jobs", signal ? { signal } : {});
}

export function fetchChatPolicies(signal?: AbortSignal) {
  return api.get<ChatPolicyList>("/api/admin/chat-policies", signal ? { signal } : {});
}

// Both writes return the whole list, so the page never has to reconcile a local
// mutation against what the server actually stored.
export function setChatPolicy(chatId: number, patch: ChatPolicyPatch) {
  return api.put<ChatPolicyList>(`/api/admin/chat-policies/${chatId}`, patch);
}

export function deleteChatPolicy(chatId: number) {
  return api.delete<ChatPolicyList>(`/api/admin/chat-policies/${chatId}`);
}
