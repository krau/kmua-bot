"""Request and response models for the Mini App API.

Validation lives here rather than in the routers, so an invalid payload is
rejected before it can reach the database. Field constraints mirror the column
limits in `kmua.database.models`.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from kmua.enums import VerifyFailAction, VerifyMethod, VerifyTrigger
from kmua.i18n import i18n

# Keys accepted by /t, matching plugins/title/utils.py exactly. A stricter set
# than "any bool" so a typo cannot silently create a permission that is never read.
TITLE_PERMISSION_KEYS: frozenset[str] = frozenset(
    {
        "can_change_info",
        "can_delete_messages",
        "can_manage_tags",
        "can_restrict_members",
        "can_invite_users",
        "can_promote_members",
        "can_post_stories",
        "can_edit_stories",
        "can_delete_stories",
        "can_manage_video_chats",
        "can_manage_topics",
        "can_pin_messages",
    }
)

# The economy floor mirrors `cost_user_coins`, which clamps at -144*16.
COINS_MIN = -144 * 16
COINS_MAX = 10**9
AFFECTION_MIN = -(10**6)
AFFECTION_MAX = 10**6


def _valid_locale(value: str) -> str:
    available = i18n.get_available_locales()
    if value not in available:
        raise ValueError(f"unsupported locale, expected one of {sorted(available)}")
    return value


LocaleStr = Annotated[str, Field(min_length=1, max_length=32)]


class ApiModel(BaseModel):
    """Base model: reject unknown keys so typos surface instead of being ignored."""

    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------- auth


class AuthRequest(ApiModel):
    init_data_raw: str = Field(min_length=1, max_length=8192)


class SessionUserOut(ApiModel):
    id: int
    full_name: str
    username: str | None = None
    is_bot_global_admin: bool = False


class AuthResponse(ApiModel):
    token: str
    expires_at: int
    user: SessionUserOut
    roles: list[str]
    # Chat id decoded from ?startapp=, for navigation only.
    start_chat_id: int | None = None


# ----------------------------------------------------------------------------- me


class MeOut(ApiModel):
    id: int
    full_name: str
    username: str | None
    lang: str
    coins: int
    affection: int
    affection_percentile: float | None
    waifu_mention: bool
    is_married: bool
    married_waifu_id: int | None
    married_waifu_name: str | None
    quote_count: int
    gift_count: int
    chat_count: int
    roles: list[str]


class MeConfigPatch(ApiModel):
    """Partial update. Only fields present in the payload are applied."""

    lang: LocaleStr | None = None
    waifu_mention: bool | None = None

    @field_validator("lang")
    @classmethod
    def _check_lang(cls, value: str | None) -> str | None:
        return None if value is None else _valid_locale(value)


class ChatBriefOut(ApiModel):
    id: int
    title: str
    username: str | None
    can_manage: bool


class QuoteOut(ApiModel):
    link: str
    chat_id: int
    chat_title: str | None = None
    user_id: int
    user_name: str | None = None
    message_id: int
    text: str | None
    has_image: bool
    created_at: str


class WaifuEntryOut(ApiModel):
    chat_id: int
    chat_title: str
    waifu_id: int | None
    waifu_name: str | None


class WaifuOut(ApiModel):
    is_married: bool
    married_waifu_id: int | None
    married_waifu_name: str | None
    entries: list[WaifuEntryOut]


class GiftOut(ApiModel):
    id: int
    gift_id: str
    display_name: str
    rarity: int
    rarity_name: str
    sent_to_bot: bool
    created_at: str


class GiftCatalogOut(ApiModel):
    gift_id: str
    display_name: str
    description: str
    comment: str
    price: int


class GiftPurchaseIn(ApiModel):
    gift_id: str


class GiftUseOut(ApiModel):
    gift: GiftOut
    detail: str | None = None


# -------------------------------------------------------------------------- chats


class VerifyQuestionIn(ApiModel):
    question: str = Field(min_length=1, max_length=200)
    options: list[str] = Field(min_length=2, max_length=6)
    answers: list[str] = Field(min_length=1, max_length=6)
    # 多正确答案的判定模式: all = 全选, any = 任选其一即可
    select: str = "all"

    @field_validator("select")
    @classmethod
    def _check_select(cls, value: str) -> str:
        if value not in {"all", "any"}:
            raise ValueError("select must be 'all' or 'any'")
        return value

    @field_validator("question")
    @classmethod
    def _strip_question(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("question must not be blank")
        return stripped

    @field_validator("options")
    @classmethod
    def _normalize_options(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        for option in value:
            stripped = option.strip()
            if not stripped:
                continue
            if stripped in cleaned:
                continue
            cleaned.append(stripped)
        if len(cleaned) < 2:
            raise ValueError("options must have at least 2 non-blank entries")
        if any(len(option) > 100 for option in cleaned):
            raise ValueError("option too long")
        return cleaned

    @field_validator("answers")
    @classmethod
    def _normalize_answers(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        for answer in value:
            stripped = answer.strip()
            if not stripped:
                continue
            if stripped in cleaned:
                continue
            cleaned.append(stripped)
        if not cleaned:
            raise ValueError("answers must have at least 1 non-blank entry")
        return cleaned

    @model_validator(mode="after")
    def _check_answers_in_options(self) -> VerifyQuestionIn:
        unknown = [a for a in self.answers if a not in self.options]
        if unknown:
            raise ValueError(f"answers must be options, got: {unknown}")
        return self


class VerifyQuestionsIn(ApiModel):
    questions: list[VerifyQuestionIn] = Field(max_length=200)


class VerifyQuestionOut(ApiModel):
    question: str
    options: list[str]
    answers: list[str]
    select: str = "all"  # 旧数据无此字段, 默认全选


class VerifyQuestionsOut(ApiModel):
    questions: list[VerifyQuestionOut]


class ChatConfigOut(ApiModel):
    """The full ChatConfig, sent and received as one document.

    Whole-document writes keep the panel and the inline keyboard from racing on
    partial updates of the same JSON column.
    """

    waifu_enabled: bool
    delete_events_enabled: bool
    unpin_channel_pin_enabled: bool
    quote_probability: float
    quote_pin_message: bool
    title_permissions: dict[str, bool]
    greeting: str | None
    ai_reply: bool
    ai_reply_other_bots_enabled: bool
    ai_comment: bool
    setu_enabled: bool
    convert_b23_enabled: bool
    parse_links_enabled: bool
    parse_artwork_enabled: bool
    parse_sites_enabled: dict[str, bool] = {}
    pick_bottle_enabled: bool
    group_memory_enabled: bool
    sticker_memory_enabled: bool
    parse_wechat_enabled: bool
    rss_agent_summary: bool
    rss_agent_broadcast: bool
    verify_enabled: bool
    verify_strategy: str
    verify_method: str
    verify_max_attempts: int
    verify_timeout_seconds: int
    verify_fail_action: str
    verify_questions: list[VerifyQuestionOut] = []
    lang: str


class ChatConfigIn(ApiModel):
    waifu_enabled: bool
    delete_events_enabled: bool
    unpin_channel_pin_enabled: bool
    quote_probability: float = Field(ge=0.0, le=1.0)
    quote_pin_message: bool
    greeting: str | None = Field(default=None, max_length=1024)
    ai_reply: bool
    ai_reply_other_bots_enabled: bool
    ai_comment: bool
    setu_enabled: bool
    convert_b23_enabled: bool
    parse_links_enabled: bool
    parse_artwork_enabled: bool
    parse_sites_enabled: dict[str, bool] = {}
    pick_bottle_enabled: bool
    group_memory_enabled: bool
    sticker_memory_enabled: bool
    parse_wechat_enabled: bool
    rss_agent_summary: bool
    rss_agent_broadcast: bool
    verify_enabled: bool
    verify_strategy: str
    verify_method: str
    verify_max_attempts: int = Field(ge=1, le=10)
    verify_timeout_seconds: int = Field(ge=30, le=600)
    verify_fail_action: str
    lang: LocaleStr

    @field_validator("lang")
    @classmethod
    def _check_lang(cls, value: str) -> str:
        return _valid_locale(value)

    @field_validator("verify_strategy")
    @classmethod
    def _check_verify_strategy(cls, value: str) -> str:
        if value not in {m.value for m in VerifyTrigger}:
            raise ValueError(
                f"unsupported verify strategy, expected one of {[m.value for m in VerifyTrigger]}"
            )
        return value

    @field_validator("verify_method")
    @classmethod
    def _check_verify_method(cls, value: str) -> str:
        if value not in {m.value for m in VerifyMethod}:
            raise ValueError(
                f"unsupported verify method, expected one of {[m.value for m in VerifyMethod]}"
            )
        return value

    @field_validator("verify_fail_action")
    @classmethod
    def _check_verify_fail_action(cls, value: str) -> str:
        if value not in {m.value for m in VerifyFailAction}:
            raise ValueError(
                f"unsupported verify fail action, expected one of {[m.value for m in VerifyFailAction]}"
            )
        return value

    @field_validator("greeting")
    @classmethod
    def _normalize_greeting(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class TitlePermissionsIn(ApiModel):
    permissions: dict[str, bool]

    @field_validator("permissions")
    @classmethod
    def _check_keys(cls, value: dict[str, bool]) -> dict[str, bool]:
        unknown = set(value) - TITLE_PERMISSION_KEYS
        if unknown:
            raise ValueError(f"unknown permissions: {sorted(unknown)}")
        return value


class ChatDetailOut(ApiModel):
    id: int
    title: str
    username: str | None
    member_count: int
    quote_count: int
    config: ChatConfigOut
    created_at: str
    can_manage: bool
    is_blocked: bool


class ChatAdminOut(ApiModel):
    user_id: int
    full_name: str
    username: str | None
    promoted_by: int | None
    promoted_by_name: str | None


class ChatAdminIn(ApiModel):
    user_id: int


class SyncMembersOut(ApiModel):
    removed: int
    checked: int


class RssSubscriptionOut(ApiModel):
    id: int
    feed_id: int
    url: str
    title: str | None
    paused: bool
    # None means the subscription follows the global rss_interval.
    interval_minutes: int | None
    last_error: str | None
    last_fetched_at: str
    created_at: str


class RssSubscriptionIn(ApiModel):
    url: str = Field(min_length=1, max_length=1024)


class RssSubscriptionPatch(ApiModel):
    """A subscription write. Absent fields keep their current value."""

    paused: bool | None = None
    interval_minutes: int | None = Field(
        default=None, ge=1, le=1440, description="Minutes; null = global default"
    )


# -------------------------------------------------------------------------- admin


class StatsOut(ApiModel):
    users: int
    chats: int
    quotes: int
    associations: int
    bottles: int
    affection: dict[str, Any]
    runtime: dict[str, Any]
    dashboard: dict[str, Any]


class ConfigSnapshotOut(ApiModel):
    groups: dict[str, dict[str, Any]]
    secrets: dict[str, str | None]
    agent_providers: dict[str, dict[str, str | None]]
    owners_count: int


class ConfigReloadOut(ApiModel):
    success: bool
    message: str
    changed_fields: list[str]


class AdminChatOut(ApiModel):
    id: int
    title: str
    username: str | None
    member_count: int
    created_at: str
    is_blocked: bool


class AdminUserOut(ApiModel):
    id: int
    full_name: str
    username: str | None
    lang: str
    coins: int
    affection: int
    waifu_mention: bool
    is_bot: bool
    is_real_user: bool
    is_bot_global_admin: bool
    is_blocked: bool
    is_owner: bool
    is_married: bool
    married_waifu_id: int | None
    created_at: str


class AdminUserDetailOut(AdminUserOut):
    chats: list[ChatBriefOut]
    quote_count: int
    gift_count: int


class AdminUserPatch(ApiModel):
    """Partial user edit. Absent fields are left alone.

    `coins`, `affection` and `is_bot_global_admin` require owner rights; the
    router reports rejected fields in `skipped` rather than failing the request.
    """

    lang: LocaleStr | None = None
    waifu_mention: bool | None = None
    full_name: str | None = Field(default=None, min_length=1, max_length=256)
    username: str | None = Field(default=None, max_length=64)
    coins: int | None = Field(default=None, ge=COINS_MIN, le=COINS_MAX)
    affection: int | None = Field(default=None, ge=AFFECTION_MIN, le=AFFECTION_MAX)
    is_bot_global_admin: bool | None = None
    # Only unmarrying is supported: marriages are made in-chat.
    is_married: Literal[False] | None = None

    @field_validator("lang")
    @classmethod
    def _check_lang(cls, value: str | None) -> str | None:
        return None if value is None else _valid_locale(value)


class FieldChangeOut(ApiModel):
    field: str
    old: Any
    new: Any


class SkippedFieldOut(ApiModel):
    field: str
    reason: str


class AdminUserPatchOut(ApiModel):
    changed: list[FieldChangeOut]
    skipped: list[SkippedFieldOut]
    user: AdminUserDetailOut


class JobOut(ApiModel):
    id: str
    name: str | None
    trigger: str
    next_run_time: str | None


# ----------------------------------------------------------------- chat policy


class ChatPolicyFlagsOut(ApiModel):
    """The operator-controlled flags for one chat.

    One model per flag set rather than a bare dict, so adding a flag is a typed change
    the frontend sees rather than a key that silently appears.
    """

    agent_allowed: bool
    rss_allowed: bool


class ChatPolicyOut(ApiModel):
    chat_id: int
    # None when the bot has never seen the chat, so the panel shows the id alone.
    chat_title: str | None
    policy: ChatPolicyFlagsOut
    updated_by: int | None
    note: str | None
    created_at: str


class ChatPolicyListOut(ApiModel):
    """The rows, plus the config flags that decide whether they mean anything.

    `agent_whitelist_mode` is reported alongside the list because the list is inert
    without it: with the mode off the agent answers everywhere regardless, and the UI
    has to say so rather than implying these are the only allowed chats.
    """

    agent_whitelist_mode: bool
    rss_whitelist_mode: bool
    items: list[ChatPolicyOut]


class ChatPolicyDetailOut(ApiModel):
    """One chat's policy, plus the mode flags that decide whether it is inert.

    The detail view has the same honesty problem as the list: a flag shown as
    "on" while its whitelist mode is off would imply it does something. The modes
    travel with the row so the page can say so in place.
    """

    agent_whitelist_mode: bool
    rss_whitelist_mode: bool
    item: ChatPolicyOut


class ChatPolicyIn(ApiModel):
    """A policy write. Absent flags keep their current value."""

    agent_allowed: bool | None = None
    rss_allowed: bool | None = None
    note: str | None = Field(default=None, max_length=256)


class PageOut[T](ApiModel):
    items: list[T]
    total: int
    page: int
    size: int
