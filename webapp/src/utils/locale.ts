/**
 * Display names for the locales the bot ships.
 *
 * A raw tag like `zh-Hant` is fine in a config file and wrong in a picker: the
 * person choosing a language reads their own language's name, not a BCP 47 tag.
 * The list is explicit rather than `Intl.DisplayNames` because kmua ships joke
 * locales (Martian, 🤪) that no CLDR table knows, and because each name should be
 * written in the language it selects - that is what makes it findable.
 *
 * Unknown tags fall through to the tag itself, so a locale added to the bot shows
 * up in the panel immediately instead of disappearing.
 */

const DISPLAY_NAMES: Record<string, string> = {
  "zh-CN": "简体中文",
  "zh-Hant": "繁體中文",
  en: "English",
  "ja-JP": "日本語",
  "ko-KR": "한국어",
  Martian: "火星文",
  "🤪": "🤪",
};

/** The name to show for a locale tag. */
export function localeName(tag: string): string {
  return DISPLAY_NAMES[tag] ?? tag;
}
