"""Request and response models for the Mini App API.

Validation lives here rather than in the routers, so an invalid payload is
rejected before it can reach the database. Field constraints mirror the column
limits in `kmua.database.models`.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

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


# -------------------------------------------------------------------------- chats


class ChatConfigOut(ApiModel):
    """The full ChatConfig, sent and received as one document.

    Whole-document writes keep the panel and the inline keyboard from racing on
    partial updates of the same JSON column.
    """

    waifu_enabled: bool
    delete_events_enabled: bool
    unpin_channel_pin_enabled: bool
    message_search_enabled: bool
    quote_probability: float
    quote_pin_message: bool
    title_permissions: dict[str, bool]
    greeting: str | None
    ai_reply: bool
    ai_reply_other_bots_enabled: bool
    ai_comment: bool
    setu_enabled: bool
    convert_b23_enabled: bool
    parse_artwork_enabled: bool
    pick_bottle_enabled: bool
    group_memory_enabled: bool
    lang: str


class ChatConfigIn(ApiModel):
    waifu_enabled: bool
    delete_events_enabled: bool
    unpin_channel_pin_enabled: bool
    message_search_enabled: bool
    quote_probability: float = Field(ge=0.0, le=1.0)
    quote_pin_message: bool
    greeting: str | None = Field(default=None, max_length=1024)
    ai_reply: bool
    ai_reply_other_bots_enabled: bool
    ai_comment: bool
    setu_enabled: bool
    convert_b23_enabled: bool
    parse_artwork_enabled: bool
    pick_bottle_enabled: bool
    group_memory_enabled: bool
    lang: LocaleStr

    @field_validator("lang")
    @classmethod
    def _check_lang(cls, value: str) -> str:
        return _valid_locale(value)

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


# -------------------------------------------------------------------------- admin


class StatsOut(ApiModel):
    users: int
    chats: int
    quotes: int
    associations: int
    bottles: int
    affection: dict[str, Any]


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

    agent_enabled: bool


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
    items: list[ChatPolicyOut]


class ChatPolicyIn(ApiModel):
    """A policy write. Absent flags keep their current value."""

    agent_enabled: bool | None = None
    note: str | None = Field(default=None, max_length=256)


class PageOut[T](ApiModel):
    items: list[T]
    total: int
    page: int
    size: int
