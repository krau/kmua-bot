/**
 * How the chat config is presented.
 *
 * `ChatConfig` is a flat bag of sixteen booleans in the order they accumulated in
 * the codebase. Rendering them in that order would be a wall of unrelated switches,
 * so they are grouped by what they affect - which is the difference between a
 * settings page and a dump of the schema.
 *
 * Keeping the grouping here rather than inline in the view means a new config flag is
 * one line in one place, and the view stays a renderer.
 */

import type { ChatConfig } from "@/api/types";

/** Boolean keys of ChatConfig, i.e. the ones rendered as a toggle. */
export type ChatToggleKey = {
  [K in keyof ChatConfig]: ChatConfig[K] extends boolean ? K : never;
}[keyof ChatConfig];

export interface ToggleGroup {
  /** i18n key under `chats.` for the group label. */
  labelKey: string;
  keys: ChatToggleKey[];
}

export const TOGGLE_GROUPS: ToggleGroup[] = [
  {
    labelKey: "interaction",
    keys: ["waifu_enabled", "quote_pin_message", "pick_bottle_enabled"],
  },
  {
    labelKey: "ai",
    keys: ["ai_reply", "ai_reply_other_bots_enabled", "ai_comment", "group_memory_enabled"],
  },
  {
    labelKey: "content",
    keys: [
      "setu_enabled",
      "convert_b23_enabled",
      "parse_artwork_enabled",
      "message_search_enabled",
    ],
  },
  {
    labelKey: "housekeeping",
    keys: ["delete_events_enabled", "unpin_channel_pin_enabled"],
  },
];

/**
 * Settings that need a line of explanation.
 *
 * Only these. A hint under every row is noise that trains people to skip all of
 * them, so the ones whose name does not carry its meaning get one and the rest do
 * not.
 */
export const TOGGLES_WITH_HINTS: ReadonlySet<ChatToggleKey> = new Set<ChatToggleKey>([
  "group_memory_enabled",
]);

/** The 12 /t permission keys, in the order they are rendered. */
export const TITLE_PERMISSION_KEYS = [
  "can_change_info",
  "can_delete_messages",
  "can_manage_tags",
  "can_pin_messages",
  "can_invite_users",
  "can_restrict_members",
  "can_promote_members",
  "can_manage_topics",
  "can_manage_video_chats",
  "can_post_stories",
  "can_edit_stories",
  "can_delete_stories",
] as const;

export type TitlePermissionKey = (typeof TITLE_PERMISSION_KEYS)[number];
