/**
 * Bind Telegram's native back button to the router.
 *
 * Installed once at app level: the button is shown on every route except the home
 * screen, and pressing it walks the router history. Drawing our own back arrow
 * inside the page would duplicate a control the client already provides at the
 * position users reach for.
 */

import { onScopeDispose, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import { navButton } from "@/telegram";

export function useBackButton(): void {
  const router = useRouter();
  const route = useRoute();

  const off = navButton.onClick(() => {
    if (window.history.state?.back) {
      router.back();
      return;
    }
    // Deep-linked straight into a subpage: there is no history to pop.
    void router.replace({ name: "home" });
  });

  watch(
    () => route.name,
    (name) => {
      if (name === "home") {
        navButton.hide();
      } else {
        navButton.show();
      }
    },
    { immediate: true },
  );

  onScopeDispose(() => {
    off();
    navButton.hide();
  });
}
