/**
 * Contrast fallback for client-supplied theme colours.
 *
 * The hint and separator colours come from the user's Telegram theme, and some
 * themes put them below the WCAG AA minimum of 4.5:1 against the background. When
 * that happens the panel switches to colours we control instead of shipping text
 * that some users cannot read.
 */

const AA_CONTRAST = 4.5;

function parseHex(color: string): [number, number, number] | null {
  const value = color.trim();
  const match = /^#?([\da-f]{3}|[\da-f]{6})$/i.exec(value);
  if (!match?.[1]) return null;
  let hex = match[1];
  if (hex.length === 3) {
    hex = hex
      .split("")
      .map((char) => char + char)
      .join("");
  }
  return [
    Number.parseInt(hex.slice(0, 2), 16),
    Number.parseInt(hex.slice(2, 4), 16),
    Number.parseInt(hex.slice(4, 6), 16),
  ];
}

/** Relative luminance per WCAG 2.x. */
function luminance([r, g, b]: [number, number, number]): number {
  const channel = (value: number): number => {
    const scaled = value / 255;
    return scaled <= 0.03928 ? scaled / 12.92 : ((scaled + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

export function contrastRatio(foreground: string, background: string): number | null {
  const fg = parseHex(foreground);
  const bg = parseHex(background);
  if (!fg || !bg) return null;
  const lighter = Math.max(luminance(fg), luminance(bg));
  const darker = Math.min(luminance(fg), luminance(bg));
  return (lighter + 0.05) / (darker + 0.05);
}

/**
 * Measure the theme's hint colour and set `data-contrast` on `<html>`.
 *
 * Runs after the SDK has bound the theme variables. When the ratio cannot be
 * measured (a theme may omit a colour entirely) the fallback is applied, because
 * an unknown contrast is not a safe one.
 */
export function applyContrastFallback(): void {
  const root = document.documentElement;
  const styles = getComputedStyle(root);
  const hint = styles.getPropertyValue("--tg-theme-hint-color");
  const background = styles.getPropertyValue("--tg-theme-bg-color");

  if (!hint.trim() || !background.trim()) {
    root.removeAttribute("data-contrast");
    return;
  }

  const ratio = contrastRatio(hint, background);
  if (ratio === null || ratio < AA_CONTRAST) {
    root.setAttribute("data-contrast", "fallback");
  } else {
    root.removeAttribute("data-contrast");
  }
}
