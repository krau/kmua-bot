/**
 * Minimal i18n.
 *
 * Two locales, flat JSON, dot-path lookup with `{placeholder}` interpolation. A
 * library would add a dependency and a plugin lifecycle for what fits here in
 * forty lines - and error text is keyed by the backend's error codes, so the
 * lookup shape is fixed anyway.
 */

import { computed, ref } from "vue";

import en from "./en.json";
import zhCN from "./zh-CN.json";

type Messages = Record<string, unknown>;

const CATALOGUES: Record<string, Messages> = {
  "zh-CN": zhCN,
  en,
};

const FALLBACK_LOCALE = "zh-CN";

const currentLocale = ref(FALLBACK_LOCALE);

export const locale = computed(() => currentLocale.value);

/**
 * Point the UI at a locale.
 *
 * kmua ships locales the panel does not (Martian, zh-Hant and friends), so an
 * unknown value falls back rather than emptying the interface. `zh-Hant` is mapped
 * to `zh-CN` because it is far closer than English.
 */
export function setLocale(value: string): void {
  if (value in CATALOGUES) {
    currentLocale.value = value;
    return;
  }
  if (value.startsWith("zh")) {
    currentLocale.value = "zh-CN";
    return;
  }
  if (value.startsWith("en")) {
    currentLocale.value = "en";
    return;
  }
  currentLocale.value = FALLBACK_LOCALE;
}

function lookup(catalogue: Messages, path: string): string | undefined {
  let node: unknown = catalogue;
  for (const key of path.split(".")) {
    if (typeof node !== "object" || node === null) return undefined;
    node = (node as Record<string, unknown>)[key];
  }
  return typeof node === "string" ? node : undefined;
}

function interpolate(template: string, params?: Record<string, string | number>): string {
  if (!params) return template;
  return template.replace(/\{(\w+)\}/g, (match, key: string) => {
    const value = params[key];
    return value === undefined ? match : String(value);
  });
}

/** Translate `path`, falling back to the default locale and then to the path. */
export function t(path: string, params?: Record<string, string | number>): string {
  const active = CATALOGUES[currentLocale.value];
  const fallback = CATALOGUES[FALLBACK_LOCALE];
  const template =
    (active ? lookup(active, path) : undefined) ??
    (fallback ? lookup(fallback, path) : undefined) ??
    path;
  return interpolate(template, params);
}

/** Optional lookup: returns undefined instead of the path when absent. */
export function tOptional(path: string): string | undefined {
  const active = CATALOGUES[currentLocale.value];
  const fallback = CATALOGUES[FALLBACK_LOCALE];
  return (
    (active ? lookup(active, path) : undefined) ?? (fallback ? lookup(fallback, path) : undefined)
  );
}

/** Human text for a backend error code, with a generic fallback. */
export function tError(code: string): string {
  return tOptional(`errors.${code}`) ?? t("errors.INTERNAL_ERROR");
}

export function useI18n() {
  return { t, tError, tOptional, locale, setLocale };
}
