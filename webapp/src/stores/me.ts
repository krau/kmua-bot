/**
 * The caller's own profile, cached for the session.
 *
 * Held in a store rather than fetched per view because several pages need the same
 * record (home for the role cards, profile for the fields, quotes for the count)
 * and it changes only when this user edits it.
 */

import { defineStore } from "pinia";
import { ref } from "vue";

import { fetchMe, updateMyConfig } from "@/api/endpoints/me";
import type { Me, MeConfigPatch } from "@/api/types";
import { setLocale } from "@/i18n";

export const useMeStore = defineStore("me", () => {
  const me = ref<Me | null>(null);
  const loading = ref(false);
  // The shell warms this store up while a view may ask for the same record; both
  // should share one request instead of racing two.
  let pending: Promise<Me> | null = null;

  async function load(force = false): Promise<Me> {
    if (me.value && !force) return me.value;
    if (pending && !force) return pending;

    loading.value = true;
    pending = (async () => {
      try {
        const data = await fetchMe();
        me.value = data;
        // The user's stored language is the panel's language.
        setLocale(data.lang);
        return data;
      } finally {
        loading.value = false;
        pending = null;
      }
    })();
    return pending;
  }

  async function save(patch: MeConfigPatch): Promise<Me> {
    const data = await updateMyConfig(patch);
    me.value = data;
    setLocale(data.lang);
    return data;
  }

  return { me, loading, load, save };
});
