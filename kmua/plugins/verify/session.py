"""验证会话的生命周期: 注册表、持久化、sweep 与 Telegram 动作。"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from pyrogram.client import Client
from pyrogram.errors import RPCError
from pyrogram.raw.functions.messages.edit_message import EditMessage
from pyrogram.types import (
    Chat,
    ChatPermissions,
    InlineKeyboardMarkup,
    InputRichMessage,
    Message,
    User,
)

from kmua import common, database
from kmua.bot.client import client
from kmua.database.models import ChatConfig, VerificationSession
from kmua.i18n import i18n
from kmua.logger import logger
from kmua.plugins.verify.challenge import (
    RESTORE_PERMISSIONS_KEY,
    _challenge_markup,
    build_challenge_text,
    make_emoji_challenge,
    make_math_challenge,
    make_math_hard_challenge,
    make_qa_challenge,
    restore_permissions_for_session,
)

RESULT_MESSAGE_TTL = 30

# 贴纸验证失败时删除用户窗口期消息的上限。
MAX_WINDOW_MESSAGE_DELETE = 300

# --------------------------------------------------------------------------- 会话注册表
# DB 为准, 内存为 O(1) 查询缓存: session_id -> session, (chat_id, user_id) -> session_id

_sessions: dict[int, VerificationSession] = {}
_by_user: dict[tuple[int, int], int] = {}
_user_locks: dict[tuple[int, int], asyncio.Lock] = {}
_user_lock_refs: dict[tuple[int, int], int] = {}


@asynccontextmanager
async def verification_lock(chat_id: int, user_id: int):
    """Serialize session creation and completion for one chat member."""
    key = (chat_id, user_id)
    lock = _user_locks.setdefault(key, asyncio.Lock())
    _user_lock_refs[key] = _user_lock_refs.get(key, 0) + 1
    try:
        async with lock:
            yield
    finally:
        refs = _user_lock_refs[key] - 1
        if refs == 0:
            _user_lock_refs.pop(key, None)
            if _user_locks.get(key) is lock:
                _user_locks.pop(key, None)
        else:
            _user_lock_refs[key] = refs


def _register(session_row: VerificationSession) -> None:
    _sessions[session_row.id] = session_row
    _by_user[(session_row.chat_id, session_row.user_id)] = session_row.id


def _unregister(session_id: int) -> None:
    session_row = _sessions.pop(session_id, None)
    if session_row is None:
        return
    if _by_user.get((session_row.chat_id, session_row.user_id)) == session_id:
        _by_user.pop((session_row.chat_id, session_row.user_id), None)


def _get_for(chat_id: int, user_id: int) -> VerificationSession | None:
    session_id = _by_user.get((chat_id, user_id))
    if session_id is None:
        return None
    return _sessions.get(session_id)


async def capture_restore_permissions(
    bot: Client,
    chat_id: int,
    user_id: int,
) -> ChatPermissions | None:
    """捕获成员已有的自定义限制; 普通成员返回 None, 验证后全放开。"""
    try:
        member = await bot.get_chat_member(chat_id, user_id)
    except Exception as e:
        logger.warning(
            f"verify: failed to read permissions for {user_id} in {chat_id}: {e}"
        )
        return None
    return getattr(member, "permissions", None)


async def _cleanup_session(session_row: VerificationSession) -> None:
    """删 DB 行并移出注册表。"""
    try:
        await database.delete_verification_session(session_row.id)
    except Exception as e:
        logger.error(f"verify: failed to delete session {session_row.id}: {e}")
    _unregister(session_row.id)


async def _delete_message_later(chat_id: int, message_id: int) -> None:
    """延迟删除结果提示消息; 失败静默。"""
    await asyncio.sleep(RESULT_MESSAGE_TTL)
    try:
        await client.delete_messages(chat_id, message_id)
    except RPCError as e:
        logger.debug(f"verify: failed to auto-delete message {message_id}: {e}")


def _schedule_result_delete(chat_id: int, message_id: int | None) -> None:
    """结果提示消息过 TTL 后自动删除。"""
    if message_id is not None:
        common.spawn(_delete_message_later(chat_id, message_id))


async def _user_mention(user: User | Chat | int) -> str:
    """目标用户/频道的 HTML mention; 获取失败时退化为 id 链接。"""
    try:
        if isinstance(user, int):
            fetched = await client.get_users(user)
            target: User | Chat = fetched[0] if isinstance(fetched, list) else fetched
        else:
            target = user
        return await common.mention_html(target)
    except (RPCError, ValueError):
        user_id = getattr(user, "id", None) or user
        return f"<a href='tg://user?id={user_id}'>User</a>"


async def _delete_user_messages_in_window(session_row: VerificationSession) -> None:
    """删除用户从入群到验证失败期间发送的消息(贴纸方式无限制, 失败兜底)。"""
    created_at = session_row.created_at
    if created_at is None:
        return
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    message_ids: list[int] = []
    try:
        async for message in client.search_messages(
            session_row.chat_id,
            from_user=session_row.user_id,
            min_date=created_at,
            max_date=datetime.now(UTC),
        ):
            message_ids.append(message.id)
            if len(message_ids) >= MAX_WINDOW_MESSAGE_DELETE:
                break
    except RPCError as e:
        logger.warning(
            f"verify: failed to search history for session {session_row.id}: {e}"
        )
        return
    if not message_ids:
        return
    try:
        for start in range(0, len(message_ids), 100):
            await client.delete_messages(
                session_row.chat_id, message_ids[start : start + 100]
            )
    except RPCError as e:
        logger.warning(
            f"verify: failed to delete window messages for session {session_row.id}: {e}"
        )


async def _chat_config(chat_id: int) -> ChatConfig | None:
    """读群配置; 聊天已删返回 None。"""
    try:
        return await database.get_chat_config(chat_id)
    except ValueError:
        return None


def _is_expired(session_row: VerificationSession) -> bool:
    """SQLite 读回的 naive UTC 补时区后再比较。"""
    expires_at = session_row.expires_at
    if expires_at is None:
        return False
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return expires_at <= datetime.now(UTC)


async def restore_member_permissions(
    bot: Client, session_row: VerificationSession
) -> None:
    """Restore the pre-verification permissions without granting new rights."""
    permissions = restore_permissions_for_session(session_row)
    if permissions is None:
        return
    try:
        await bot.restrict_chat_member(
            session_row.chat_id, session_row.user_id, permissions
        )
    except Exception as e:
        logger.error(
            f"verify: failed to restore permissions for {session_row.user_id} "
            f"in {session_row.chat_id}: {e}"
        )


# --------------------------------------------------------------------------- 生命周期


async def load_active_sessions() -> None:
    """启动时把 DB 会话灌入注册表。"""
    try:
        sessions = await database.get_all_verification_sessions()
    except Exception as e:
        logger.error(f"verify: failed to load active sessions: {e}")
        return
    for session_row in sessions:
        _register(session_row)
    if sessions:
        logger.info(f"verify: restored {len(sessions)} active verification session(s)")


async def verify_sweep() -> None:
    """超时/群停用/聊天删除的周期兜底; 单条失败不中断其余。"""
    try:
        sessions = await database.get_all_verification_sessions()
    except Exception as e:
        logger.error(f"verify: sweep failed to load sessions: {e}")
        return
    for session_row in sessions:
        try:
            config = await _chat_config(session_row.chat_id)
            if config is None:
                # 聊天已删, 静默清理
                await _cleanup_session(session_row)
                continue
            if not config.verify_enabled:
                await _cancel_session(session_row)
                continue
            if _is_expired(session_row):
                await _fail_session(session_row, "timeout")
        except Exception:
            logger.exception(f"verify: sweep error on session {session_row.id}")


async def handle_user_left(chat_id: int, user_id: int) -> None:
    """用户退群/被 ban: 删 DB 行并移出注册表。"""
    try:
        await database.delete_verification_sessions_for_user(chat_id, user_id)
    except Exception as e:
        logger.error(
            f"verify: failed to delete sessions for {user_id} in {chat_id}: {e}"
        )
    session_id = _by_user.pop((chat_id, user_id), None)
    if session_id is not None:
        _unregister(session_id)


def _to_rich_html(text: str) -> str:
    """rich 消息的 html 模式不保留换行, 显式转为 <br>。"""
    return text.replace("\n", "<br>")


async def _send_challenge(
    bot: Client,
    chat_id: int,
    session_row: VerificationSession,
    config: ChatConfig,
    lang: str,
    user_mention: str = "",
) -> Message:
    """发送 challenge 消息; 失败向上抛由调用方处理。"""
    text = build_challenge_text(
        config,
        session_row.method,
        session_row.payload or {},
        session_row.attempts_left,
        wrong_prefix=False,
        lang=lang,
        user_mention=user_mention,
    )
    if session_row.method == "math_hard":
        # rich 消息: <tg-math> 公式走 html 模式, 换行显式转 <br>
        return await bot.send_rich_message(
            chat_id,
            InputRichMessage(html=_to_rich_html(text)),
            reply_markup=_challenge_markup(session_row, lang),
        )
    return await bot.send_message(
        chat_id, text, reply_markup=_challenge_markup(session_row, lang)
    )


async def _edit_challenge_message(
    bot: Client,
    session_row: VerificationSession,
    text: str,
    markup: InlineKeyboardMarkup | None,
) -> None:
    """编辑 challenge 消息; math_hard 是 rich 消息, 用 EditMessage.rich_message。"""
    if session_row.challenge_message_id is None:
        return
    if session_row.method == "math_hard":
        peer = await bot.resolve_peer(session_row.chat_id)
        if peer is None:
            return
        extra: dict[str, Any] = {}
        if markup is not None:
            written = await markup.write(bot)
            if written is not None:
                extra["reply_markup"] = written
        await bot.invoke(
            EditMessage(
                peer=peer,
                id=session_row.challenge_message_id,
                rich_message=InputRichMessage(html=_to_rich_html(text)).write(),
                **extra,
            )
        )
    elif markup is None:
        await bot.edit_message_text(
            session_row.chat_id, session_row.challenge_message_id, text
        )
    else:
        await bot.edit_message_text(
            session_row.chat_id,
            session_row.challenge_message_id,
            text,
            reply_markup=markup,
        )


async def _fail_session(session_row: VerificationSession, reason: str) -> None:
    """验证失败(超时/次数耗尽): 删 challenge, 按群配置动作处理用户, 发通知。"""
    config = await _chat_config(session_row.chat_id)
    if config is None:
        await _cleanup_session(session_row)
        return
    lang = config.lang
    action = config.verify_fail_action

    if session_row.challenge_message_id is not None:
        try:
            await client.delete_messages(
                session_row.chat_id, session_row.challenge_message_id
            )
        except RPCError as e:
            logger.debug(f"verify: failed to delete challenge {session_row.id}: {e}")

    if session_row.method == "sticker":
        # 贴纸方式不限制发言, 失败时删除用户窗口期消息兜底
        await _delete_user_messages_in_window(session_row)

    if action == "kick":
        # ban + unban: 移出但不拉黑, 可重新加群再验证
        try:
            await client.ban_chat_member(session_row.chat_id, session_row.user_id)
        except RPCError as e:
            logger.error(f"verify: kick ban failed for {session_row.user_id}: {e}")
        try:
            await client.unban_chat_member(session_row.chat_id, session_row.user_id)
        except RPCError as e:
            logger.error(f"verify: kick unban failed for {session_row.user_id}: {e}")
    elif action == "ban":
        try:
            await client.ban_chat_member(session_row.chat_id, session_row.user_id)
        except RPCError as e:
            logger.error(f"verify: ban failed for {session_row.user_id}: {e}")
    else:  # unrestrict
        await restore_member_permissions(client, session_row)

    try:
        prefix = i18n.t(f"bot.msg.verify.{reason}_prefix", locale=lang).format(
            user=await _user_mention(session_row.user_id)
        )
        suffix = i18n.t(f"bot.msg.verify.action_{action}", locale=lang)
        notice = await client.send_message(session_row.chat_id, prefix + suffix)
        _schedule_result_delete(session_row.chat_id, notice.id)
    except (RPCError, ValueError) as e:
        logger.debug(f"verify: failed to notify failure for {session_row.id}: {e}")

    await _cleanup_session(session_row)


async def _cancel_session(session_row: VerificationSession) -> None:
    """群停用验证: 解除验证施加的限制, 删 challenge, 清会话。"""
    await restore_member_permissions(client, session_row)
    if session_row.challenge_message_id is not None:
        try:
            await client.delete_messages(
                session_row.chat_id, session_row.challenge_message_id
            )
        except RPCError as e:
            logger.debug(f"verify: failed to delete challenge {session_row.id}: {e}")
    await _cleanup_session(session_row)


async def _succeed_session(session_row: VerificationSession, lang: str) -> None:
    """验证通过(或管理员放行): 改成功文案, 解除限制, 清会话。"""
    if session_row.challenge_message_id is not None:
        try:
            await _edit_challenge_message(
                client,
                session_row,
                i18n.t("bot.msg.verify.success", locale=lang).format(
                    user=await _user_mention(session_row.user_id)
                ),
                None,
            )
        except RPCError as e:
            logger.debug(f"verify: failed to edit challenge {session_row.id}: {e}")
    _schedule_result_delete(session_row.chat_id, session_row.challenge_message_id)
    await restore_member_permissions(client, session_row)
    try:
        await database.mark_user_verified(session_row.chat_id, session_row.user_id)
    except Exception as e:
        logger.error(f"verify: failed to mark verified {session_row.id}: {e}")
    await _cleanup_session(session_row)


async def _admin_ban_session(session_row: VerificationSession, lang: str) -> None:
    """管理员手动封禁(恒为永久拉黑)。"""
    if session_row.challenge_message_id is not None:
        try:
            await _edit_challenge_message(
                client,
                session_row,
                i18n.t("bot.msg.verify.admin_banned", locale=lang).format(
                    user=await _user_mention(session_row.user_id)
                ),
                None,
            )
        except RPCError as e:
            logger.debug(f"verify: failed to edit challenge {session_row.id}: {e}")
    _schedule_result_delete(session_row.chat_id, session_row.challenge_message_id)
    try:
        await client.ban_chat_member(session_row.chat_id, session_row.user_id)
    except RPCError as e:
        logger.error(f"verify: admin ban failed for {session_row.user_id}: {e}")
    await _cleanup_session(session_row)


# --------------------------------------------------------------------------- 内部工具


async def _wrong_answer(
    session_row: VerificationSession,
    config: ChatConfig,
    lang: str,
    *,
    edit_message: Message | None = None,
) -> None:
    """答错: 扣次数; 耗尽则失败, 否则换新题并刷新文案。"""
    session_row.attempts_left -= 1
    if session_row.attempts_left <= 0:
        await _fail_session(session_row, "failed")
        return
    new_payload: dict = {}
    if session_row.method == "math_easy":
        new_payload = make_math_challenge()
    elif session_row.method == "math_hard":
        new_payload = make_math_hard_challenge(lang)
    elif session_row.method == "emoji":
        new_payload = make_emoji_challenge()
    elif session_row.method == "custom_qa":
        new_payload = make_qa_challenge(config.verify_questions, lang)
    restore_permissions = (session_row.payload or {}).get(RESTORE_PERMISSIONS_KEY)
    if restore_permissions is not None:
        new_payload[RESTORE_PERMISSIONS_KEY] = restore_permissions
    session_row.payload = new_payload
    await database.update_verification_session(session_row)
    if edit_message is not None:
        try:
            await _edit_challenge_message(
                client,
                session_row,
                build_challenge_text(
                    config,
                    session_row.method,
                    session_row.payload or {},
                    session_row.attempts_left,
                    wrong_prefix=True,
                    lang=lang,
                    user_mention=await _user_mention(session_row.user_id),
                ),
                _challenge_markup(session_row, lang),
            )
        except RPCError as e:
            logger.debug(f"verify: failed to refresh challenge {session_row.id}: {e}")
