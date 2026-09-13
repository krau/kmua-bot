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

export interface VerifyQuestion {
  question: string;
  options: string[];
  answers: string[];
  /** 多正确答案的判定模式: all = 全选, any = 任选其一即可。 */
  select: string;
}

export interface VerifyQuestions {
  questions: VerifyQuestion[];
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
  parse_links_enabled: boolean;
  parse_artwork_enabled: boolean;
  /** Per-site link-parsing switches; an absent key defaults to enabled. */
  parse_sites_enabled: Record<string, boolean>;
  pick_bottle_enabled: boolean;
  group_memory_enabled: boolean;
  sticker_memory_enabled: boolean;
  parse_wechat_enabled: boolean;
  rss_agent_summary: boolean;
  rss_agent_broadcast: boolean;
  verify_enabled: boolean;
  verify_strategy: string;
  verify_method: string;
  verify_max_attempts: number;
  verify_timeout_seconds: number;
  verify_fail_action: string;
  verify_questions: VerifyQuestion[];
  lang: string;
}

/**
 * The config payload the API accepts: everything except title_permissions and
 * verify_questions, which have their own whole-set endpoints.
 */
export type ChatConfigInput = Omit<ChatConfig, "title_permissions" | "verify_questions">;

export interface ChatDetail {
  id: number;
  title: string;
  username: string | null;
  member_count: number;
  quote_count: number;
  config: ChatConfig;
  created_at: string;
  can_manage: boolean;
  is_blocked: boolean;
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
  is_blocked: boolean;
}

/**
 * One quota account's snapshot for today, in tokens (input + output).
 *
 * `scope` is "user" (the speaker) or "chat" (the conversation). `free_limit_tokens` is
 * null when no limit applies, which is not the same as 0 left; a chat account with
 * `free_limit_tokens` 0 has no shared allowance allocated. `credits` can go negative:
 * a run's usage is only known once it finishes, so an overshoot is booked as debt.
 */
export interface AgentUsage {
  scope: string;
  scope_id: number;
  requests_today: number;
  free_used_tokens_today: number;
  free_limit_tokens: number | null;
  credits: number;
  input_tokens_today: number;
  output_tokens_today: number;
  exempt: boolean;
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
  is_blocked: boolean;
  is_owner: boolean;
  is_married: boolean;
  married_waifu_id: number | null;
  created_at: string;
  chats: ChatBrief[];
  quote_count: number;
  gift_count: number;
  /** Only the detail endpoint reads this; the list leaves it null. */
  agent_quota: AgentUsage | null;
}

export interface AdminUserPatch {
  lang?: string;
  waifu_mention?: boolean;
  full_name?: string;
  username?: string;
  coins?: number;
  affection?: number;
  agent_credits?: number;
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
  agent_quota_daily_tokens: number;
  agent_quota_exempt: boolean;
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
  agent_quota: AgentUsage;
}

/** A policy write. Absent flags keep their current value. */
export interface ChatPolicyPatch {
  agent_allowed?: boolean | null;
  rss_allowed?: boolean | null;
  note?: string | null;
  agent_quota_daily_tokens?: number | null;
  agent_quota_exempt?: boolean | null;
  agent_credits?: number | null;
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

/**
 * What triggered a run. Mirrors `RUN_KINDS` in `kmua/database/agent_trace.py`.
 */
export type AgentRunKind =
  | "chat"
  | "ask"
  | "followup"
  | "followup_relevance"
  | "channel_comment"
  | "rss_digest"
  | "rss_broadcast"
  | "sticker_description"
  | "memory"
  | "transcription"
  | "compaction";

/** How a run ended. Mirrors `RUN_STATUSES`. */
export type AgentRunStatus = "ok" | "error" | "timeout" | "cancelled" | "rejected";

/** One recorded step. Mirrors `EVENT_KINDS`. */
export type AgentRunEventKind =
  "model_request" | "model_response" | "tool_call" | "tool_result" | "steering" | "error";

/** A run without its heavy text fields; the list view uses this. */
export interface AgentRunSummary {
  id: number;
  kind: AgentRunKind;
  status: AgentRunStatus;
  /** Only set for a rejected run: "quota" or "whitelist". */
  reject_reason: string | null;
  /**
   * The conversation instance this run belongs to (random, one per chat+user thread).
   * Null for runs with no conversation of their own, such as RSS work.
   */
  session_id: string | null;
  chat_id: number | null;
  user_id: number | null;
  message_id: number | null;
  parent_run_id: number | null;
  model_name: string | null;
  model_role: string | null;
  streaming: boolean;
  started_at: string;
  finished_at: string;
  duration_ms: number;
  requests: number;
  tool_calls: number;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cache_write_tokens: number;
  output_kind: string | null;
  output_chars: number | null;
  error_class: string | null;
  event_count: number;
  events_dropped: number;
}

/** One step of a run, without its payload. */
export interface AgentRunEvent {
  seq: number;
  kind: AgentRunEventKind;
  name: string | null;
  status: string;
  duration_ms: number | null;
  payload_chars: number | null;
  truncated: boolean;
  created_at: string;
}

export interface AgentRunDetail extends AgentRunSummary {
  output_text: string | null;
  error_message: string | null;
  events: AgentRunEvent[];
}

export interface AgentRunEventDetail extends AgentRunEvent {
  payload: Record<string, unknown> | null;
  /**
   * The messages the model received, rebuilt from the run's prefix encoding.
   * Only present for `model_request` steps, and null when it cannot be rebuilt.
   */
  messages: unknown[] | null;
}

/** Filters for the run list; empty values are dropped from the query string. */
export interface AgentRunQuery {
  page: number;
  size: number;
  session_id?: string;
  chat_id?: number;
  user_id?: number;
  kind?: string;
  status?: string;
  q?: string;
  since?: string;
  until?: string;
}
