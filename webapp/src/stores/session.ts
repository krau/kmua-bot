/**
 * Session state: the authenticated user, their roles, and the session token.
 *
 * The token lives here in memory and nowhere else. A Mini App re-authenticates from
 * initData every launch, so persisting it would only widen the attack surface.
 */

import { defineStore } from "pinia";
import { computed, ref } from "vue";

import { authenticate } from "@/api/endpoints/auth";
import { setReauthenticator, setSessionToken } from "@/api/client";
import type { Role, SessionUser } from "@/api/types";
import { launchContext } from "@/telegram";

export const useSessionStore = defineStore("session", () => {
  const user = ref<SessionUser | null>(null);
  const roles = ref<Role[]>([]);
  const startChatId = ref<number | null>(null);
  const expiresAt = ref(0);

  const isAuthenticated = computed(() => user.value !== null);
  const isOwner = computed(() => roles.value.includes("owner"));
  const isGlobalAdmin = computed(() => roles.value.includes("global_admin"));
  /** Owner or global admin: may enter the developer panel. */
  const isBotAdmin = computed(() => isOwner.value || isGlobalAdmin.value);

  async function signIn(): Promise<void> {
    const { initDataRaw, startChatId: deepLinkChat } = launchContext();
    if (!initDataRaw) {
      throw new Error("NO_INIT_DATA");
    }

    const response = await authenticate(initDataRaw);
    setSessionToken(response.token);
    user.value = response.user;
    roles.value = response.roles;
    expiresAt.value = response.expires_at;
    // Prefer the value the server decoded; fall back to the SDK's own parse.
    startChatId.value = response.start_chat_id ?? deepLinkChat;

    // Let the HTTP client recover from a 401 without bouncing the user out.
    setReauthenticator(async () => {
      const refreshed = await authenticate(initDataRaw);
      user.value = refreshed.user;
      roles.value = refreshed.roles;
      expiresAt.value = refreshed.expires_at;
      return refreshed.token;
    });
  }

  /** Consume the deep-link chat id so a later navigation does not re-trigger it. */
  function takeStartChatId(): number | null {
    const value = startChatId.value;
    startChatId.value = null;
    return value;
  }

  return {
    user,
    roles,
    expiresAt,
    startChatId,
    isAuthenticated,
    isOwner,
    isGlobalAdmin,
    isBotAdmin,
    signIn,
    takeStartChatId,
  };
});
