"""Group configuration endpoints for chat admins.

Authorization comes from `require_chat_admin`, which resolves per request via
`common.can_user_manage_bot_in_chat`. Every route in this module therefore acts on
a chat the caller has already been proven able to manage.
"""

from __future__ import annotations

from fastapi import APIRouter, Path, Query, Request

from kmua import common, database
from kmua.common import ops
from kmua.config import app_config
from kmua.database.models import ChatConfig
from kmua.logger import logger
from kmua.webapp import audit
from kmua.webapp.deps import ChatAdminCtx, client_key
from kmua.webapp.errors import ApiError, ErrorCode, not_found
from kmua.webapp.ratelimit import write_limiter
from kmua.webapp.schemas import (
    TITLE_PERMISSION_KEYS,
    ChatAdminIn,
    ChatAdminOut,
    ChatConfigIn,
    ChatConfigOut,
    ChatDetailOut,
    PageOut,
    QuoteOut,
    SyncMembersOut,
    TitlePermissionsIn,
)
from kmua.webapp.serializers import chat_config_out, quote_out

router = APIRouter(prefix="/api/chats", tags=["chats"])

# Mirrors the bot-side result codes onto HTTP semantics.
_BOT_ADMIN_ERRORS = {
    ops.BotAdminResult.INVALID_TARGET: (ErrorCode.VALIDATION_FAILED, "Invalid target"),
    ops.BotAdminResult.TARGET_IS_UPSTREAM: (
        ErrorCode.FORBIDDEN,
        "Cannot act on the admin who promoted you",
    ),
    ops.BotAdminResult.USER_NOT_FOUND: (ErrorCode.USER_NOT_FOUND, "User not found"),
    ops.BotAdminResult.USER_IS_BOT: (ErrorCode.VALIDATION_FAILED, "Target is a bot"),
    ops.BotAdminResult.USER_NOT_IN_CHAT: (
        ErrorCode.USER_NOT_FOUND,
        "User is not in this chat",
    ),
    ops.BotAdminResult.ALREADY_SET: (ErrorCode.CONFLICT, "Already in that state"),
}


@router.get("/{chat_id}", response_model=ChatDetailOut)
async def read_chat(ctx: ChatAdminCtx) -> ChatDetailOut:
    chat = ctx.chat
    return ChatDetailOut(
        id=chat.id,
        title=chat.title,
        username=chat.username,
        member_count=await database.count_chat_members(chat.id),
        quote_count=await database.count_chat_quotes(chat.id),
        config=chat_config_out(chat.chat_config),
        created_at=chat.created_at.isoformat() if chat.created_at else "",
        can_manage=True,
    )


@router.put("/{chat_id}/config", response_model=ChatConfigOut)
async def update_chat_config(
    request: Request, ctx: ChatAdminCtx, payload: ChatConfigIn
) -> ChatConfigOut:
    """Replace the chat configuration.

    Whole-document writes rather than a patch: the config is one JSON column that
    the inline /config keyboard also writes, and full replacement makes the
    last writer's intent unambiguous instead of interleaving partial updates.

    `title_permissions` is deliberately not part of this payload - it has its own
    endpoint, so saving the toggles page cannot wipe the permissions page.
    """
    write_limiter.check(client_key(request, ctx.user.id))

    current = ctx.chat.chat_config
    new_config = ChatConfig(
        waifu_enabled=payload.waifu_enabled,
        delete_events_enabled=payload.delete_events_enabled,
        unpin_channel_pin_enabled=payload.unpin_channel_pin_enabled,
        message_search_enabled=payload.message_search_enabled,
        quote_probability=payload.quote_probability,
        quote_pin_message=payload.quote_pin_message,
        title_permissions=current.title_permissions,
        greeting=payload.greeting,
        ai_reply=payload.ai_reply,
        ai_reply_other_bots_enabled=payload.ai_reply_other_bots_enabled,
        ai_comment=payload.ai_comment,
        setu_enabled=payload.setu_enabled,
        convert_b23_enabled=payload.convert_b23_enabled,
        parse_artwork_enabled=payload.parse_artwork_enabled,
        pick_bottle_enabled=payload.pick_bottle_enabled,
        group_memory_enabled=payload.group_memory_enabled,
        lang=payload.lang,
    )

    changes = [
        audit.FieldChange(field=name, old=old, new=new)
        for name, old, new in _diff_config(current, new_config)
    ]
    saved = await database.update_chat_config(ctx.chat.id, new_config)

    if changes:
        audit.record(
            action="chat.config.update",
            actor_id=ctx.user.id,
            actor_roles=ctx.user.roles,
            target=ctx.chat.id,
            changes=changes,
        )
    return chat_config_out(saved)


def _diff_config(old: ChatConfig, new: ChatConfig):
    """Yield (field, old, new) for every changed field.

    `title_permissions` is excluded: it is carried over untouched by this endpoint
    and has its own audit trail.
    """
    for name in new.to_dict():
        if name == "title_permissions":
            continue
        old_value = getattr(old, name)
        new_value = getattr(new, name)
        if old_value != new_value:
            yield name, old_value, new_value


@router.put("/{chat_id}/title-permissions", response_model=ChatConfigOut)
async def update_title_permissions(
    request: Request, ctx: ChatAdminCtx, payload: TitlePermissionsIn
) -> ChatConfigOut:
    """Set which admin rights the /t command grants.

    Unlisted keys default to false, so the payload is the complete desired state.
    """
    write_limiter.check(client_key(request, ctx.user.id))

    config = ctx.chat.chat_config
    permissions = {
        key: bool(payload.permissions.get(key, False))
        for key in sorted(TITLE_PERMISSION_KEYS)
    }
    old_permissions = config.title_permissions or {}
    config.title_permissions = permissions
    saved = await database.update_chat_config(ctx.chat.id, config)

    audit.record(
        action="chat.title_permissions.update",
        actor_id=ctx.user.id,
        actor_roles=ctx.user.roles,
        target=ctx.chat.id,
        changes=[
            audit.FieldChange(
                field=key,
                old=bool(old_permissions.get(key, False)),
                new=value,
            )
            for key, value in permissions.items()
            if bool(old_permissions.get(key, False)) != value
        ],
    )
    return chat_config_out(saved)


@router.get("/{chat_id}/admins", response_model=list[ChatAdminOut])
async def list_chat_admins(ctx: ChatAdminCtx) -> list[ChatAdminOut]:
    rows = await database.get_chat_bot_admins(ctx.chat.id)
    promoter_ids = {promoted_by for _, promoted_by in rows if promoted_by}
    promoters = {}
    for promoter_id in promoter_ids:
        promoter = await database.get_user_by_id(promoter_id)
        if promoter:
            promoters[promoter_id] = promoter.full_name

    return [
        ChatAdminOut(
            user_id=user.id,
            full_name=user.full_name,
            username=user.username,
            promoted_by=promoted_by,
            promoted_by_name=promoters.get(promoted_by) if promoted_by else None,
        )
        for user, promoted_by in rows
    ]


@router.post("/{chat_id}/admins", response_model=list[ChatAdminOut])
async def promote_chat_admin(
    request: Request, ctx: ChatAdminCtx, payload: ChatAdminIn
) -> list[ChatAdminOut]:
    write_limiter.check(client_key(request, ctx.user.id))
    await _set_bot_admin(ctx, payload.user_id, promote=True)
    return await list_chat_admins(ctx)


@router.delete("/{chat_id}/admins/{user_id}", response_model=list[ChatAdminOut])
async def demote_chat_admin(
    request: Request,
    ctx: ChatAdminCtx,
    user_id: int = Path(description="User to demote"),
) -> list[ChatAdminOut]:
    write_limiter.check(client_key(request, ctx.user.id))
    await _set_bot_admin(ctx, user_id, promote=False)
    return await list_chat_admins(ctx)


async def _set_bot_admin(ctx: ChatAdminCtx, target_id: int, *, promote: bool) -> None:
    result = await ops.set_bot_admin(
        chat_id=ctx.chat.id,
        actor_id=ctx.user.id,
        target_id=target_id,
        promote=promote,
        actor_is_privileged=ctx.user.is_admin,
    )
    if result is not ops.BotAdminResult.OK:
        code, message = _BOT_ADMIN_ERRORS[result]
        raise ApiError(code, message, 409 if code == ErrorCode.CONFLICT else 400)

    audit.record(
        action="chat.admin.promote" if promote else "chat.admin.demote",
        actor_id=ctx.user.id,
        actor_roles=ctx.user.roles,
        target=f"{target_id}@{ctx.chat.id}",
    )


@router.post("/{chat_id}/sync-members", response_model=SyncMembersOut)
async def sync_members(request: Request, ctx: ChatAdminCtx) -> SyncMembersOut:
    """Drop members the bot recorded who have since left.

    Shares the /syncmembers cooldown key, so the panel cannot be used to bypass it.
    """
    write_limiter.check(client_key(request, ctx.user.id))

    cooldown_key = f"sync_members:{ctx.chat.id}"
    if await common.memttlcache.get(cooldown_key):
        raise ApiError(ErrorCode.COOLDOWN, "Members were synced recently")
    await common.memttlcache.set(
        cooldown_key, True, app_config.cachettl_sync_members
    )

    try:
        result = await ops.sync_chat_members(ctx.chat.id)
    except Exception as e:
        logger.error(f"webapp: sync members failed for {ctx.chat.id}: {e}")
        raise ApiError(
            ErrorCode.TELEGRAM_ERROR,
            "Could not read the member list, the bot may need admin rights",
        ) from e

    audit.record(
        action="chat.members.sync",
        actor_id=ctx.user.id,
        actor_roles=ctx.user.roles,
        target=ctx.chat.id,
        extra={"removed": result.removed},
    )
    return SyncMembersOut(removed=result.removed, checked=result.checked)


@router.get("/{chat_id}/quotes", response_model=PageOut[QuoteOut])
async def list_chat_quotes(
    ctx: ChatAdminCtx,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    q: str = Query("", max_length=128, description="Search quote text"),
) -> PageOut[QuoteOut]:
    result = await database.get_chat_quotes_paged(
        ctx.chat.id, page=page, size=size, query=q
    )
    return PageOut[QuoteOut](
        items=[quote_out(quote, chat_title=ctx.chat.title) for quote in result.items],
        total=result.total,
        page=result.page,
        size=result.size,
    )


@router.delete("/{chat_id}/quotes/{link:path}", status_code=204)
async def delete_chat_quote(
    request: Request,
    ctx: ChatAdminCtx,
    link: str = Path(description="Full message link identifying the quote"),
) -> None:
    """Delete a quote from this chat.

    The quote's chat is checked against the authorized chat: the link is
    client-supplied, so without this a chat admin could delete quotes elsewhere.
    """
    write_limiter.check(client_key(request, ctx.user.id))

    quote = await database.get_quote_by_link(link)
    if quote is None or quote.chat_id != ctx.chat.id:
        raise not_found(ErrorCode.QUOTE_NOT_FOUND, "Quote not found")
    await database.delete_quote(link)

    audit.record(
        action="chat.quote.delete",
        actor_id=ctx.user.id,
        actor_roles=ctx.user.roles,
        target=f"{ctx.chat.id}",
        extra={"link": link},
    )
