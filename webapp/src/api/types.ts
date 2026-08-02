/**
 * Types mirroring `kmua/webapp/schemas.py`.
 *
 * Hand-written rather than generated: the API surface is small, and keeping these
 * by hand means a backend change shows up as a TypeScript error here instead of
 * silently passing through a generated `any`.
 */

export type Role = "user" | "global_admin" | "owner";

export interface SessionUser {
  id: number;
  full_name: string;
  username: string | null;
  is_bot_global_admin: boolean;
}

export interface AuthResponse {
  token: string;
  expires_at: number;
  user: SessionUser;
  roles: Role[];
  start_chat_id: number | null;
}

export interface SystemInfo {
  bot_username: string | null;
  panel_enabled: boolean;
  available_locales: string[];
}

export interface Me {
  id: number;
  full_name: string;
  username: string | null;
  lang: string;
  coins: number;
  affection: number;
  affection_percentile: number | null;
  waifu_mention: boolean;
  is_married: boolean;
  married_waifu_id: number | null;
  married_waifu_name: string | null;
  quote_count: number;
  gift_count: number;
  chat_count: number;
  roles: Role[];
}

export interface MeConfigPatch {
  lang?: string;
  waifu_mention?: boolean;
}

export interface ChatBrief {
  id: number;
  title: string;
  username: string | null;
  can_manage: boolean;
}

export interface Quote {
  link: string;
  chat_id: number;
  chat_title: string | null;
  user_id: number;
  user_name: string | null;
  message_id: number;
  text: string | null;
  has_image: boolean;
  created_at: string;
}

export interface WaifuEntry {
  chat_id: number;
  chat_title: string;
  waifu_id: number | null;
  waifu_name: string | null;
}

export interface Waifu {
  is_married: boolean;
  married_waifu_id: number | null;
  married_waifu_name: string | null;
  entries: WaifuEntry[];
}

export interface Gift {
  id: number;
  gift_id: string;
  display_name: string;
  rarity: number;
  rarity_name: string;
  sent_to_bot: boolean;
  created_at: string;
}

export interface GiftCatalogItem {
  gift_id: string;
  display_name: string;
  description: string;
  comment: string;
  price: number;
}

export interface GiftUseResult {
  gift: Gift;
  detail: string | null;
}

export interface ChatConfig {
  waifu_enabled: boolean;
  delete_events_enabled: boolean;
  unpin_channel_pin_enabled: boolean;
  quote_probability: number;
  quote_pin_message: boolean;
  title_permissions: Record<string, boolean>;
  greeting: string | null;
  ai_reply: boolean;
  ai_reply_other_bots_enabled: boolean;
  ai_comment: boolean;
  setu_enabled: boolean;
  convert_b23_enabled: boolean;
  parse_artwork_enabled: boolean;
  /** Per-site link-parsing switches; an absent key defaults to enabled. */
  parse_sites_enabled: Record<string, boolean>;
  pick_bottle_enabled: boolean;
  group_memory_enabled: boolean;
  parse_wechat_enabled: boolean;
  rss_agent_summary: boolean;
  rss_agent_broadcast: boolean;
  lang: string;
}

/** The config payload the API accepts: everything except title_permissions. */
export type ChatConfigInput = Omit<ChatConfig, "title_permissions">;

export interface ChatDetail {
  id: number;
  title: string;
  username: string | null;
  member_count: number;
  quote_count: number;
  config: ChatConfig;
  created_at: string;
  can_manage: boolean;
}

export interface ChatAdmin {
  user_id: number;
  full_name: string;
  username: string | null;
  promoted_by: number | null;
  promoted_by_name: string | null;
}

export interface SyncMembersResult {
  removed: number;
  checked: number;
}

export interface AffectionStats {
  total_users?: number;
  bucket_count?: number;
  min_bucket?: number;
  max_bucket?: number;
}

export interface RuntimeStats {
  uptime_seconds: number;
  max_rss_bytes: number;
  threads: number;
  tasks: number;
  loop_lag_ms: number | null;
  loop_lag_p95_ms: number | null;
  loop_lag_max_ms: number | null;
  loop_stalls: number;
  telegram_update_types: Record<string, number>;
  group_activity: Array<{ chat_id: number; events: number }>;
  feature_calls: Record<string, number>;
  telegram_updates: Record<string, number>;
  api_requests: Record<string, number>;
  api_latency_ms: { p95: number | null };
}

export interface DashboardStats {
  users: number;
  user_structure: Record<string, number>;
  recent: Record<string, number>;
  bottle_interactions: Record<string, number>;
}

export interface Stats {
  users: number;
  chats: number;
  quotes: number;
  associations: number;
  bottles: number;
  affection: AffectionStats;
  runtime: RuntimeStats;
  dashboard: DashboardStats;
}

export type ConfigValue = string | number | boolean | null | string[];

export interface ConfigSnapshot {
  groups: Record<string, Record<string, ConfigValue>>;
  secrets: Record<string, string | null>;
  agent_providers: Record<string, Record<string, string | null>>;
  owners_count: number;
}

export interface ConfigReloadResult {
  success: boolean;
  message: string;
  changed_fields: string[];
}

export interface AdminChat {
  id: number;
  title: string;
  username: string | null;
  member_count: number;
  created_at: string;
}

export interface AdminUser {
  id: number;
  full_name: string;
  username: string | null;
  lang: string;
  coins: number;
  affection: number;
  waifu_mention: boolean;
  is_bot: boolean;
  is_real_user: boolean;
  is_bot_global_admin: boolean;
  is_owner: boolean;
  is_married: boolean;
  married_waifu_id: number | null;
  created_at: string;
  chats: ChatBrief[];
  quote_count: number;
  gift_count: number;
}

export interface AdminUserPatch {
  lang?: string;
  waifu_mention?: boolean;
  full_name?: string;
  username?: string;
  coins?: number;
  affection?: number;
  is_bot_global_admin?: boolean;
  is_married?: false;
}

export interface FieldChange {
  field: string;
  old: unknown;
  new: unknown;
}

export interface SkippedField {
  field: string;
  reason: string;
}

export interface AdminUserPatchResult {
  changed: FieldChange[];
  skipped: SkippedField[];
  user: AdminUser;
}

export interface Job {
  id: string;
  name: string | null;
  trigger: string;
  next_run_time: string | null;
}

/**
 * Operator-controlled flags for one chat.
 *
 * Distinct from `ChatConfig`, which the chat's own admins edit. A new operator-only
 * per-chat setting is a field here, not a new endpoint.
 */
export interface ChatPolicyFlags {
  agent_allowed: boolean;
  rss_allowed: boolean;
}

export interface ChatPolicy {
  chat_id: number;
  /** Null when the bot has never seen the chat, so only the id can be shown. */
  chat_title: string | null;
  policy: ChatPolicyFlags;
  updated_by: number | null;
  note: string | null;
  created_at: string;
}

export interface ChatPolicyList {
  /** Whether whitelist mode is on. With it off `agent_allowed` is inert. */
  agent_whitelist_mode: boolean;
  /** Whether whitelist mode is on. With it off `rss_allowed` is inert. */
  rss_whitelist_mode: boolean;
  items: ChatPolicy[];
}

/** One chat's policy plus the mode flags that decide whether it is inert. */
export interface ChatPolicyDetail {
  agent_whitelist_mode: boolean;
  rss_whitelist_mode: boolean;
  item: ChatPolicy;
}

/** A policy write. Absent flags keep their current value. */
export interface ChatPolicyPatch {
  agent_allowed?: boolean | null;
  rss_allowed?: boolean | null;
  note?: string | null;
}

export interface RssSubscription {
  id: number;
  feed_id: number;
  url: string;
  title: string | null;
  paused: boolean;
  /** Minutes; null = follow the global poll interval. */
  interval_minutes: number | null;
  last_error: string | null;
  last_fetched_at: string;
  created_at: string;
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  size: number;
}
