/* global URLSearchParams, document, location */
import { createPinia } from "pinia";
import { createApp } from "vue";

import App from "@/preview/PreviewShell.vue";
import { installMockApi } from "./mock-api";
import { setLocale } from "@/i18n";
import { router } from "@/router";
import { useSessionStore } from "@/stores/session";
import "@/styles/main.css";

installMockApi();
const app = createApp(App);
const pinia = createPinia();
app.use(pinia);
app.use(router);

const session = useSessionStore();
session.user = { id: 1, full_name: "小可爱", username: "kmua_fan", is_bot_global_admin: true };
session.roles = ["global_admin"];
setLocale("zh-CN");
document.documentElement.dataset.theme =
  new URLSearchParams(location.search).get("theme") === "dark" ? "dark" : "light";

await router.isReady();
app.mount("#app");
