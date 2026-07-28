/**
 * Number, date and value formatting.
 *
 * `Intl` covers everything needed here, so no date library. The locale comes from
 * the panel's own locale state, which follows the user's kmua language setting.
 */

import { locale } from "@/i18n";

export function formatNumber(value: number): string {
  return new Intl.NumberFormat(locale.value).format(value);
}

/** Format a 0..1 ratio as a percentage, keeping small values legible. */
export function formatPercent(value: number, maximumFractionDigits = 2): string {
  return new Intl.NumberFormat(locale.value, {
    style: "percent",
    maximumFractionDigits,
  }).format(value);
}

/** Format an ISO timestamp as a short local date and time. */
export function formatDateTime(iso: string): string {
  if (!iso) return "-";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "-";
  return new Intl.DateTimeFormat(locale.value, {
    dateStyle: "short",
    timeStyle: "short",
  }).format(date);
}

/** Format an ISO timestamp as a date only. */
export function formatDate(iso: string): string {
  if (!iso) return "-";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "-";
  return new Intl.DateTimeFormat(locale.value, { dateStyle: "medium" }).format(date);
}

/** Collapse whitespace and cut to length, for list previews. */
export function truncate(text: string, length = 80): string {
  const collapsed = text.replace(/\s+/g, " ").trim();
  return collapsed.length > length ? `${collapsed.slice(0, length)}…` : collapsed;
}
