"""Developer panel endpoints.

Read access requires owner or global admin. Writes that touch the economy, the
affection ranking, or the admin roster require owner, and are reported field by
field rather than rejected wholesale - a global admin editing a display name plus
a coin balance gets the name change applied and the coins reported as skipped.
"""

from __future__ import annotations

from fastapi import APIRouter, Path, Query, Request

from kmua import database
from kmua.bot.client import client
from kmua.common import jobqueue, ops
from kmua.config import app_config, reload_config
from kmua.database.models import ChatPolicy, UserData
from kmua.logger import logger
from kmua.webapp import audit
from kmua.webapp.deps import RequireAdmin, RequireOwner, client_key
from kmua.webapp.errors import ApiError, ErrorCode, forbidden, not_found
from kmua.webapp.metrics import runtime_metrics
from kmua.webapp.ratelimit import write_limiter
from kmua.webapp.sanitize import config_snapshot
from kmua.webapp.schemas import (
    AdminChatOut,
    AdminUserDetailOut,
    AdminUserPatch,
    AdminUserPatchOut,
    ChatBriefOut,
    ChatDetailOut,
    ChatPolicyDetailOut,
    ChatPolicyFlagsOut,
    ChatPolicyIn,
    ChatPolicyListOut,
    ChatPolicyOut,
    ConfigReloadOut,
    ConfigSnapshotOut,
    FieldChangeOut,
    JobOut,
    PageOut,
    SkippedFieldOut,
    StatsOut,
)
from kmua.webapp.serializers import (
    admin_chat_out,
    admin_user_out,
    chat_config_out,
    timestamp,
)

router = APIRouter(prefix="/api/admin", tags=["admin"])

# Fields whose blast radius goes beyond one user's own record.
_OWNER_ONLY_FIELDS = frozenset({"coins", "affection", "is_bot_global_admin"})


@router.get("/stats", response_model=StatsOut)
async def read_stats(user: RequireAdmin) -> StatsOut:
    stats = await ops.collect_stats()
    dashboard = await database.get_dashboard_stats()
    snapshot = runtime_metrics.snapshot()
    return StatsOut(
        users=stats["users"],  # type: ignore[arg-type]
        chats=stats["chats"],  # type: ignore[arg-type]
        quotes=stats["quotes"],  # type: ignore[arg-type]
        associations=stats["associations"],  # type: ignore[arg-type]
        bottles=stats["bottles"],  # type: ignore[arg-type]
        affection=stats["affection"],  # type: ignore[arg-type]
        runtime={
            "uptime_seconds": snapshot.uptime_seconds,
            "max_rss_bytes": snapshot.max_rss_bytes,
            "threads": snapshot.threads,
            "tasks": snapshot.tasks,
            "loop_lag_ms": snapshot.loop_lag_ms,
            "loop_lag_p95_ms": snapshot.loop_lag_p95_ms,
            "loop_lag_max_ms": snapshot.loop_lag_max_ms,
            "loop_stalls": snapshot.loop_stalls,
            "telegram_updates": snapshot.telegram_updates,
            "telegram_update_types": snapshot.telegram_update_types,
            "group_activity": snapshot.group_activity,
            "feature_calls": snapshot.feature_calls,
            "api_requests": snapshot.api_requests,
            "api_latency_ms": snapshot.api_latency_ms,
        },
        dashboard=dashboard,
    )


@router.get("/config", response_model=ConfigSnapshotOut)
async def read_config(user: RequireAdmin) -> ConfigSnapshotOut:
    """Return the running configuration with every secret replaced by a marker."""
    return ConfigSnapshotOut(**config_snapshot())


@router.post("/config/reload", response_model=ConfigReloadOut)
async def reload_runtime_config(
    request: Request, user: RequireOwner
) -> ConfigReloadOut:
    """Re-read the settings files.

    Owner only: this can change AI providers, whitelists and cost parameters in
    one shot.
    """
    write_limiter.check(client_key(request, user.id))

    success, message, changed = reload_config()
    audit.record(
        action="config.reload",
        actor_id=user.id,
        actor_roles=user.roles,
        extra={"success": success, "message": message, "changed": ",".join(changed)},
    )
    return ConfigReloadOut(success=success, message=message, changed_fields=changed)


@router.get("/chats", response_model=PageOut[AdminChatOut])
async def list_chats(
    user: RequireAdmin,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    q: str = Query("", max_length=128, description="Search title, username or id"),
) -> PageOut[AdminChatOut]:
    result = await database.get_chats_page(page=page, size=size, query=q)
    items = [
        admin_chat_out(chat, await database.count_chat_members(chat.id))
        for chat in result.items
    ]
    return PageOut[AdminChatOut](
        items=items, total=result.total, page=result.page, size=result.size
    )


@router.get("/chats/{chat_id}", response_model=ChatDetailOut)
async def read_chat(user: RequireAdmin, chat_id: int) -> ChatDetailOut:
    chat = await database.get_chat_by_id(chat_id)
    if chat is None:
        raise not_found(ErrorCode.CHAT_NOT_FOUND, "Chat not found")
    return ChatDetailOut(
        id=chat.id,
        title=chat.title,
        username=chat.username,
        member_count=await database.count_chat_members(chat.id),
        quote_count=await database.count_chat_quotes(chat.id),
        config=chat_config_out(chat.chat_config),
        created_at=timestamp(chat.created_at),
        can_manage=True,
    )


@router.post("/chats/{chat_id}/leave")
async def leave_chat(
    request: Request, user: RequireOwner, chat_id: int
) -> dict[str, bool]:
    """Make the bot leave a group and forget it.

    Owner only and irreversible: the group's quotes, waifu pairings and member
    records go with it via the FK cascades.
    """
    write_limiter.check(client_key(request, user.id))

    chat = await database.get_chat_by_id(chat_id)
    if chat is None:
        raise not_found(ErrorCode.CHAT_NOT_FOUND, "Chat not found")

    left = True
    try:
        await client.leave_chat(chat_id)
    except Exception as e:
        # Already removed on Telegram's side: still worth clearing local rows.
        left = False
        logger.warning(f"webapp: leave_chat({chat_id}) failed: {e}")

    deleted = await database.delete_chat(chat_id)
    audit.record(
        action="chat.leave",
        actor_id=user.id,
        actor_roles=user.roles,
        target=chat_id,
        extra={"title": chat.title, "left": left, "purged": deleted},
    )
    return {"left": left, "purged": deleted}


@router.get("/users", response_model=PageOut[AdminUserDetailOut])
async def list_users(
    user: RequireAdmin,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    q: str = Query("", max_length=128, description="Search name, username or id"),
    only_real: bool = Query(False, description="Exclude bots and channel senders"),
) -> PageOut[AdminUserDetailOut]:
    """List users. The list view omits per-user chats to stay one query per page."""
    result = await database.get_users_page(
        page=page, size=size, query=q, only_real=only_real
    )
    items = [
        AdminUserDetailOut(
            **admin_user_out(row).model_dump(),
            chats=[],
            quote_count=0,
            gift_count=0,
        )
        for row in result.items
    ]
    return PageOut[AdminUserDetailOut](
        items=items, total=result.total, page=result.page, size=result.size
    )


@router.get("/users/{user_id}", response_model=AdminUserDetailOut)
async def read_user(user: RequireAdmin, user_id: int) -> AdminUserDetailOut:
    target = await database.get_user_by_id(user_id)
    if target is None:
        raise not_found(ErrorCode.USER_NOT_FOUND, "User not found")
    return await _user_detail(target)


async def _user_detail(target: UserData) -> AdminUserDetailOut:
    chats = await database.get_user_chats(target.id)
    return AdminUserDetailOut(
        **admin_user_out(target).model_dump(),
        chats=[
            ChatBriefOut(
                id=chat.id,
                title=chat.title,
                username=chat.username,
                can_manage=is_bot_admin,
            )
            for chat, is_bot_admin in chats
        ],
        quote_count=await database.get_user_quote_count(target.id),
        gift_count=await database.count_user_gifts(target.id),
    )


@router.patch("/users/{user_id}", response_model=AdminUserPatchOut)
async def update_user(
    request: Request,
    user: RequireAdmin,
    payload: AdminUserPatch,
    user_id: int = Path(description="User to edit"),
) -> AdminUserPatchOut:
    """Edit a user record field by field.

    Fields the caller may not change are returned in `skipped` instead of failing
    the whole request, so a partially-permitted edit still applies what it can and
    the UI can say exactly what was refused.
    """
    if not app_config.webapp_admin_edit_user:
        raise forbidden(ErrorCode.FEATURE_DISABLED, "User editing is disabled")
    write_limiter.check(client_key(request, user.id))

    target = await database.get_user_by_id(user_id)
    if target is None:
        raise not_found(ErrorCode.USER_NOT_FOUND, "User not found")

    submitted = payload.model_dump(exclude_unset=True)
    if not submitted:
        return AdminUserPatchOut(
            changed=[], skipped=[], user=await _user_detail(target)
        )

    changed: list[audit.FieldChange] = []
    skipped: list[audit.SkippedField] = []

    # A global admin must not be able to edit an owner's record, and must not be
    # able to touch their own admin flag: either would be a path to self-elevation
    # or to locking out the operator.
    target_is_owner = target.id in app_config.owners
    if target_is_owner and not user.is_owner:
        raise forbidden(
            ErrorCode.OWNER_REQUIRED, "Only an owner can edit an owner's record"
        )

    for field, value in submitted.items():
        # An explicit `null` survives exclude_unset, but no field here treats
        # None as "clear" (`username` uses an empty string for that). Passing it
        # through would either raise in int()/bool() or store the literal
        # "None", so drop it before it reaches the writers.
        if value is None:
            skipped.append(
                audit.SkippedField(field=field, reason="null is not a valid value")
            )
            continue
        if field in _OWNER_ONLY_FIELDS and not user.is_owner:
            skipped.append(
                audit.SkippedField(field=field, reason=ErrorCode.OWNER_REQUIRED)
            )
            continue
        if field == "is_bot_global_admin" and target.id == user.id:
            skipped.append(
                audit.SkippedField(field=field, reason="cannot change own role")
            )
            continue

        applied = await _apply_user_field(target, field, value)
        if applied is not None:
            changed.append(applied)

    if changed:
        audit.record(
            action="admin.user.update",
            actor_id=user.id,
            actor_roles=user.roles,
            target=target.id,
            changes=changed,
        )

    refreshed = await database.get_user_by_id(user_id)
    if refreshed is None:
        raise not_found(ErrorCode.USER_NOT_FOUND, "User disappeared")

    return AdminUserPatchOut(
        changed=[FieldChangeOut(**change.as_dict()) for change in changed],
        skipped=[SkippedFieldOut(**item.as_dict()) for item in skipped],
        user=await _user_detail(refreshed),
    )


async def _apply_user_field(
    target: UserData, field: str, value: object
) -> audit.FieldChange | None:
    """Write one field, returning the change, or None when it was already set."""
    config = target.user_config

    match field:
        case "lang":
            if config.lang == value:
                return None
            old = config.lang
            config.lang = str(value)
            await database.update_user_config(target.id, config)
            return audit.FieldChange(field=field, old=old, new=value)

        case "coins":
            if config.coins == value:
                return None
            old = config.coins
            config.coins = int(value)  # type: ignore[arg-type]
            await database.update_user_config(target.id, config)
            return audit.FieldChange(field=field, old=old, new=value)

        case "affection":
            if config.affection == value:
                return None
            old = config.affection
            # Must go through this helper: it keeps the affection histogram
            # buckets in step, which the percentile ranking depends on. Writing
            # the JSON column directly would silently corrupt every percentile.
            await database.update_user_affection(target.id, int(value))  # type: ignore[arg-type]
            return audit.FieldChange(field=field, old=old, new=value)

        case "waifu_mention":
            old_flag = await database.set_user_waifu_mention(target.id, bool(value))
            if old_flag == value:
                return None
            return audit.FieldChange(field=field, old=old_flag, new=value)

        case "is_bot_global_admin":
            old_flag = await database.set_user_global_admin(target.id, bool(value))
            if old_flag == value:
                return None
            return audit.FieldChange(field=field, old=old_flag, new=value)

        case "full_name":
            if target.full_name == value:
                return None
            old = target.full_name
            await database.set_user_identity(target.id, full_name=str(value))
            return audit.FieldChange(field=field, old=old, new=value)

        case "username":
            if target.username == value:
                return None
            old = target.username
            await database.set_user_identity(
                target.id, username=str(value) if value else ""
            )
            return audit.FieldChange(field=field, old=old, new=value)

        case "is_married":
            # Only unmarrying is supported; `divorce` clears both sides.
            if not target.is_married:
                return None
            try:
                await database.divorce(target.id)
            except ValueError as e:
                raise ApiError(ErrorCode.NOT_MARRIED, str(e)) from e
            return audit.FieldChange(field=field, old=True, new=False)

    return None


def _chat_policy_out(row, live_title: str | None) -> ChatPolicyOut:
    """Serialize one policy row; the live title wins over the stored copy.

    The stored copy exists for chats the bot has not seen or has since been
    purged, so it is a fallback rather than a cache to refresh.
    """
    return ChatPolicyOut(
        chat_id=row.chat_id,
        chat_title=live_title or row.chat_title,
        policy=ChatPolicyFlagsOut(**row.chat_policy.to_dict()),
        updated_by=row.updated_by,
        note=row.note,
        created_at=timestamp(row.created_at),
    )


@router.get("/chat-policies", response_model=ChatPolicyListOut)
async def read_chat_policies(user: RequireAdmin) -> ChatPolicyListOut:
    """Per-chat operator policy, plus the config flags that gate it."""
    rows = await database.get_chat_policies()
    return ChatPolicyListOut(
        agent_whitelist_mode=app_config.agent_whitelist_mode,
        rss_whitelist_mode=app_config.rss_whitelist_mode,
        items=[_chat_policy_out(row, live_title) for row, live_title in rows],
    )


@router.get("/chat-policies/{chat_id}", response_model=ChatPolicyDetailOut)
async def read_chat_policy(
    user: RequireAdmin,
    chat_id: int = Path(description="Chat whose policy is shown"),
) -> ChatPolicyDetailOut:
    """One chat's policy for the detail view, with the gating modes."""
    found = await database.get_chat_policy_row(chat_id)
    if found is None:
        raise not_found(ErrorCode.NOT_FOUND, "Chat has no policy")
    row, live_title = found
    return ChatPolicyDetailOut(
        agent_whitelist_mode=app_config.agent_whitelist_mode,
        rss_whitelist_mode=app_config.rss_whitelist_mode,
        item=_chat_policy_out(row, live_title),
    )


@router.put("/chat-policies/{chat_id}", response_model=ChatPolicyListOut)
async def write_chat_policy(
    request: Request,
    user: RequireOwner,
    payload: ChatPolicyIn,
    chat_id: int = Path(description="Chat the policy applies to"),
) -> ChatPolicyListOut:
    """Set a chat's policy, creating the row if this is the first decision about it.

    Owner only: granting the agent access to a group lets it read and reply there,
    which is a wider grant than anything a global admin can make elsewhere.

    The chat does not have to be known to the bot yet - an operator onboarding a group
    can set its policy by id before the first message arrives.

    PUT with absent flags meaning "leave alone", so adding a second flag later does not
    require every client to send the full set.
    """
    write_limiter.check(client_key(request, user.id))

    current = await database.get_chat_policy(chat_id)
    desired = ChatPolicy(
        agent_allowed=(
            current.agent_allowed
            if payload.agent_allowed is None
            else payload.agent_allowed
        ),
        rss_allowed=(
            current.rss_allowed if payload.rss_allowed is None else payload.rss_allowed
        ),
    )

    old, new = await database.set_chat_policy(
        chat_id, desired, updated_by=user.id, note=payload.note
    )

    changes = [
        audit.FieldChange(field=field, old=getattr(old, field), new=getattr(new, field))
        for field in new.to_dict()
        if getattr(old, field) != getattr(new, field)
    ]
    if changes:
        audit.record(
            action="chat.policy.update",
            actor_id=user.id,
            actor_roles=user.roles,
            target=chat_id,
            changes=changes,
        )
    return await read_chat_policies(user)


@router.delete("/chat-policies/{chat_id}", response_model=ChatPolicyListOut)
async def delete_chat_policy_entry(
    request: Request, user: RequireOwner, chat_id: int
) -> ChatPolicyListOut:
    """Drop a chat's policy row, returning every flag to its default."""
    write_limiter.check(client_key(request, user.id))

    removed = await database.delete_chat_policy(chat_id)
    if not removed:
        raise not_found(ErrorCode.NOT_FOUND, "Chat has no policy")

    audit.record(
        action="chat.policy.delete",
        actor_id=user.id,
        actor_roles=user.roles,
        target=chat_id,
    )
    return await read_chat_policies(user)


@router.get("/jobs", response_model=list[JobOut])
async def list_jobs(user: RequireAdmin) -> list[JobOut]:
    """Report the scheduler's jobs. Read-only: scheduling stays in code."""
    jobs = jobqueue.get_all_jobs()
    return [
        JobOut(
            id=job.id,
            name=job.name,
            trigger=str(job.trigger),
            next_run_time=(
                job.next_run_time.isoformat()
                if getattr(job, "next_run_time", None)
                else None
            ),
        )
        for job in jobs
    ]
