/**
 * Routes.
 *
 * History mode, because the panel is served from the app root and deep links carry
 * a real path. Guards mirror the backend's tiers so a user cannot reach a page whose
 * data they will be refused anyway - the server still enforces it, this only avoids
 * showing a screen that would fail.
 */

import { createRouter, createWebHistory, type RouteRecordRaw } from "vue-router";

import { useSessionStore } from "@/stores/session";

const routes: RouteRecordRaw[] = [
  {
    path: "/",
    name: "home",
    component: () => import("@/views/HomeView.vue"),
  },
  {
    path: "/me",
    name: "me",
    component: () => import("@/views/me/ProfileView.vue"),
  },
  {
    path: "/me/quotes",
    name: "me-quotes",
    component: () => import("@/views/me/QuotesView.vue"),
  },
  {
    path: "/me/waifu",
    name: "me-waifu",
    component: () => import("@/views/me/WaifuView.vue"),
  },
  {
    path: "/me/gifts",
    name: "me-gifts",
    component: () => import("@/views/me/GiftsView.vue"),
  },
  {
    path: "/me/rss",
    name: "me-rss",
    component: () => import("@/views/me/MyRssView.vue"),
  },
  {
    path: "/chats",
    name: "chats",
    component: () => import("@/views/chats/ChatListView.vue"),
  },
  {
    path: "/chats/:chatId",
    name: "chat-config",
    component: () => import("@/views/chats/ChatConfigView.vue"),
    props: (route) => ({ chatId: Number(route.params.chatId) }),
  },
  {
    path: "/chats/:chatId/title-permissions",
    name: "chat-title-permissions",
    component: () => import("@/views/chats/TitlePermissionsView.vue"),
    props: (route) => ({ chatId: Number(route.params.chatId) }),
  },
  {
    path: "/chats/:chatId/parse-sites",
    name: "chat-parse-sites",
    component: () => import("@/views/chats/ChatParseSitesView.vue"),
    props: (route) => ({ chatId: Number(route.params.chatId) }),
  },
  {
    path: "/chats/:chatId/admins",
    name: "chat-admins",
    component: () => import("@/views/chats/ChatAdminsView.vue"),
    props: (route) => ({ chatId: Number(route.params.chatId) }),
  },
  {
    path: "/chats/:chatId/quotes",
    name: "chat-quotes",
    component: () => import("@/views/chats/ChatQuotesView.vue"),
    props: (route) => ({ chatId: Number(route.params.chatId) }),
  },
  {
    path: "/chats/:chatId/rss",
    name: "chat-rss",
    component: () => import("@/views/chats/ChatRssView.vue"),
    props: (route) => ({ chatId: Number(route.params.chatId) }),
  },
  {
    path: "/chats/:chatId/verify-questions",
    name: "chat-verify-questions",
    component: () => import("@/views/chats/VerifyQuestionsView.vue"),
    props: (route) => ({ chatId: Number(route.params.chatId) }),
  },
  {
    path: "/admin",
    name: "admin",
    component: () => import("@/views/admin/DashboardView.vue"),
    meta: { requiresBotAdmin: true },
  },
  {
    path: "/admin/config",
    name: "admin-config",
    component: () => import("@/views/admin/ConfigView.vue"),
    meta: { requiresBotAdmin: true },
  },
  {
    path: "/admin/chats",
    name: "admin-chats",
    component: () => import("@/views/admin/ChatsView.vue"),
    meta: { requiresBotAdmin: true },
  },
  {
    path: "/admin/chats/:chatId",
    name: "admin-chat",
    component: () => import("@/views/admin/ChatDetailView.vue"),
    props: (route) => ({ chatId: Number(route.params.chatId) }),
    meta: { requiresBotAdmin: true },
  },
  {
    path: "/admin/users",
    name: "admin-users",
    component: () => import("@/views/admin/UsersView.vue"),
    meta: { requiresBotAdmin: true },
  },
  {
    path: "/admin/users/:userId",
    name: "admin-user",
    component: () => import("@/views/admin/UserEditView.vue"),
    props: (route) => ({ userId: Number(route.params.userId) }),
    meta: { requiresBotAdmin: true },
  },
  {
    path: "/admin/jobs",
    name: "admin-jobs",
    component: () => import("@/views/admin/JobsView.vue"),
    meta: { requiresBotAdmin: true },
  },
  {
    path: "/admin/chat-policies",
    name: "admin-chat-policies",
    component: () => import("@/views/admin/ChatPolicyView.vue"),
    meta: { requiresBotAdmin: true },
  },
  {
    path: "/admin/chat-policies/:chatId",
    name: "admin-chat-policy",
    component: () => import("@/views/admin/ChatPolicyDetailView.vue"),
    props: (route) => ({ chatId: Number(route.params.chatId) }),
    meta: { requiresBotAdmin: true },
  },
  // Unknown paths land on the home screen rather than a 404 page: inside a Mini
  // App there is no address bar to correct a typo with.
  { path: "/:pathMatch(.*)*", redirect: { name: "home" } },
];

export const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior: () => ({ top: 0 }),
});

router.beforeEach((to) => {
  if (!to.meta.requiresBotAdmin) return true;
  const session = useSessionStore();
  return session.isBotAdmin ? true : { name: "home" };
});
