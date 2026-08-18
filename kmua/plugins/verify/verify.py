"""群聊新成员验证: Telegram 处理器(challenge 在 `challenge` 模块, 生命周期在 `session` 模块)。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pyrogram
from pyrogram.client import Client
from pyrogram.errors import RPCError
from pyrogram.types import CallbackQuery

from kmua import common, database, enums
from kmua.database.models import ChatConfig, VerificationSession
from kmua.i18n import i18n
from kmua.logger import logger
from kmua.plugins.verify.challenge import (
    RESTORE_PERMISSIONS_KEY,
    VerifyContext,
    _callback_data,
    _challenge_markup,
    _is_correct_option,
    _is_multi_answer,
    make_challenge_payload,
    restrict_permissions,
    serialize_permissions,
    strategy_matches,
)
from kmua.plugins.verify.session import (
    _admin_ban_session,
    _chat_config,
    _cleanup_session,
    _fail_session,
    _get_for,
    _is_expired,
    _register,
    _send_challenge,
    _sessions,
    _succeed_session,
    _user_mention,
    _wrong_answer,
    capture_restore_permissions,
    restore_member_permissions,
    verification_lock,
)

# 对外再导出: __main__ / chat_member 以 verify 模块为入口
from kmua.plugins.verify.session import (
    handle_user_left as handle_user_left,
)
from kmua.plugins.verify.session import (
    load_active_sessions as load_active_sessions,
)
from kmua.plugins.verify.session import (
    verify_sweep as verify_sweep,
)

# --------------------------------------------------------------------------- 处理器


@Client.on_message(pyrogram.filters.new_chat_members & pyrogram.filters.group, group=2)
async def on_new_members(client: Client, message: pyrogram.types.Message) -> None:
    """新成员入群 -> 按策略/配置验证: 限制发言 + 发 challenge。"""
    chat = message.chat
    if chat is None:
        return
    chat_id = chat.id
    if chat_id is None:
        return
    new_members = message.new_chat_members
    if not new_members:
        return
    config = await _chat_config(chat_id)
    if config is None or not config.verify_enabled:
        return
    try:
        member = await client.get_chat_member(chat_id, "me")
    except RPCError as e:
        logger.warning(f"verify: cannot check bot membership in {chat_id}: {e}")
        return
    if member.privileges is None or not member.privileges.can_restrict_members:
        # fail-open: 无权限不拦截入群
        logger.warning(
            f"verify: bot lacks can_restrict_members in {chat_id}, skipping verification"
        )
        return

    for user in new_members:
        if user is None:
            continue
        if client.me is not None and user.id == client.me.id:
            continue  # bot 自己被拉入群
        await maybe_verify(
            client,
            VerifyContext(chat_id=chat_id, user=user, is_join=True),
        )


@Client.on_callback_query(pyrogram.filters.regex(r"^verify:"), group=0)
async def on_verify_callback(client: Client, callback_query: CallbackQuery) -> None:
    """作答按钮回调: 归属校验 -> 过期兜底 -> 判对错。"""
    data = _callback_data(callback_query)
    if len(data) != 3:
        await callback_query.answer(i18n.t("bot.msg.verify.expired"), show_alert=True)
        return
    try:
        session_id = int(data[1])
    except ValueError:
        await callback_query.answer(i18n.t("bot.msg.verify.expired"), show_alert=True)
        return
    session_row = _sessions.get(session_id)
    user = callback_query.from_user
    message = callback_query.message
    chat = message.chat if message is not None else None
    if session_row is None or chat is None or user is None:
        # 会话不存在或消息缺失
        await callback_query.answer(i18n.t("bot.msg.verify.expired"), show_alert=True)
        return
    if session_row.chat_id != chat.id or user.id != session_row.user_id:
        # 越权点击
        await callback_query.answer(i18n.t("bot.msg.verify.expired"), show_alert=True)
        return
    config = await _chat_config(session_row.chat_id)
    if config is None:
        await _cleanup_session(session_row)
        await callback_query.answer(i18n.t("bot.msg.verify.expired"), show_alert=True)
        return
    lang = config.lang
    if _is_expired(session_row):
        await _fail_session(session_row, "timeout")
        await callback_query.answer(i18n.t("bot.msg.verify.expired"), show_alert=True)
        return
    payload = session_row.payload or {}
    if data[2] == "submit":
        # 多选题确认: 已选项集合与正确答案集合一致才通过
        selected = set(payload.get("selected") or [])
        options = payload.get("options") or []
        correct = {
            i
            for i, option in enumerate(options)
            if option in (payload.get("answers") or [])
        }
        if selected and selected == correct:
            await _succeed_session(session_row, lang)
            await callback_query.answer()
        else:
            await _wrong_answer(session_row, config, lang, edit_message=message)
            await callback_query.answer(
                i18n.t("bot.msg.verify.wrong_alert", locale=lang).format(
                    attempts=session_row.attempts_left, max=config.verify_max_attempts
                ),
                show_alert=True,
            )
        return
    try:
        index = int(data[2])
    except ValueError:
        await callback_query.answer(i18n.t("bot.msg.verify.expired"), show_alert=True)
        return
    if _is_multi_answer(session_row):
        # 多选题: 点选只切换勾选状态, 不判对错
        selected = set(payload.get("selected") or [])
        if index in selected:
            selected.discard(index)
        else:
            selected.add(index)
        payload["selected"] = sorted(selected)
        await database.update_verification_session(session_row)
        if message is not None:
            try:
                await message.edit_reply_markup(_challenge_markup(session_row, lang))
            except RPCError as e:
                logger.debug(f"verify: failed to refresh markup {session_row.id}: {e}")
        await callback_query.answer()
        return
    if not _is_correct_option(session_row, index):
        await _wrong_answer(session_row, config, lang, edit_message=message)
        await callback_query.answer(
            i18n.t("bot.msg.verify.wrong_alert", locale=lang).format(
                attempts=session_row.attempts_left, max=config.verify_max_attempts
            ),
            show_alert=True,
        )
        return
    await _succeed_session(session_row, lang)
    await callback_query.answer()


@Client.on_callback_query(pyrogram.filters.regex(r"^verify_admin:"), group=0)
async def on_verify_admin_callback(
    client: Client, callback_query: CallbackQuery
) -> None:
    """管理员放行/封禁按钮。权限门 = 全仓统一管理权限。"""
    data = _callback_data(callback_query)
    if len(data) != 3:
        await callback_query.answer(i18n.t("bot.msg.verify.expired"), show_alert=True)
        return
    try:
        session_id = int(data[1])
    except ValueError:
        await callback_query.answer(i18n.t("bot.msg.verify.expired"), show_alert=True)
        return
    session_row = _sessions.get(session_id)
    message = callback_query.message
    chat = message.chat if message is not None else None
    if session_row is None or chat is None:
        await callback_query.answer(i18n.t("bot.msg.verify.expired"), show_alert=True)
        return
    if session_row.chat_id != chat.id:
        await callback_query.answer(i18n.t("bot.msg.verify.expired"), show_alert=True)
        return
    user = callback_query.from_user
    if user is None:
        return
    try:
        can_manage = await common.can_user_manage_bot_in_chat(user, chat)
    except ValueError:
        can_manage = False
    if not can_manage:
        try:
            user_config = await database.get_user_config(user)
            locale = user_config.lang
        except Exception:
            locale = "zh-CN"
        await callback_query.answer(
            i18n.t("bot.msg.no_permission_group", locale=locale),
            show_alert=True,
        )
        return
    config = await _chat_config(session_row.chat_id)
    if config is None:
        await _cleanup_session(session_row)
        await callback_query.answer(i18n.t("bot.msg.verify.expired"), show_alert=True)
        return
    lang = config.lang
    if _is_expired(session_row):
        await _fail_session(session_row, "timeout")
        await callback_query.answer(i18n.t("bot.msg.verify.expired"), show_alert=True)
        return
    if data[2] == "approve":
        await _succeed_session(session_row, lang)
        await callback_query.answer()
    elif data[2] == "ban":
        await _admin_ban_session(session_row, lang)
        await callback_query.answer()
    else:
        await callback_query.answer(i18n.t("bot.msg.verify.expired"), show_alert=True)


@Client.on_message(
    pyrogram.filters.group & pyrogram.filters.sticker & pyrogram.filters.reply,
    group=-50,
)
async def on_verify_sticker_answer(
    client: Client, message: pyrogram.types.Message
) -> None:
    """贴纸作答: 任意贴纸即通过, 仅超时可能失败; group=-50 抢在 agent 前。"""
    chat = message.chat
    user = message.from_user
    if chat is None or user is None:
        return
    chat_id = chat.id
    if chat_id is None:
        return
    session_row = _get_for(chat_id, user.id)
    if session_row is None or session_row.method != "sticker":
        return
    reply_to = message.reply_to_message
    if reply_to is None or reply_to.id != session_row.challenge_message_id:
        return
    config = await _chat_config(session_row.chat_id)
    if config is None:
        await _cleanup_session(session_row)
        message.stop_propagation()
        return
    lang = config.lang
    if _is_expired(session_row):
        await _fail_session(session_row, "timeout")
        message.stop_propagation()
        return
    await _succeed_session(session_row, lang)
    message.stop_propagation()


async def maybe_verify(client: Client, ctx: VerifyContext) -> bool:
    """检查验证状态; 返回是否应拦截当前消息。"""
    config = await _chat_config(ctx.chat_id)
    if config is None or not config.verify_enabled:
        return False
    async with verification_lock(ctx.chat_id, ctx.user_id):
        ctx.has_active_session = _get_for(ctx.chat_id, ctx.user_id) is not None
        if ctx.has_active_session:
            return True
        ctx.is_verified = await database.is_user_verified(ctx.chat_id, ctx.user_id)
        if not strategy_matches(config.verify_strategy, ctx):
            return False
        return await _start_verification(client, ctx.chat_id, ctx.user, config)


async def _start_verification(
    client: Client,
    chat_id: int,
    user: pyrogram.types.User | pyrogram.types.Chat,
    config: ChatConfig,
) -> bool:
    """建会话并限制成员; 每个失败分支都尽量恢复外部状态。"""
    user_id = user.id
    if user_id is None:
        return False
    permissions = restrict_permissions(config.verify_method)
    restore_permissions = None
    if permissions is not None:
        restore_permissions = await capture_restore_permissions(
            client, chat_id, user_id
        )
    payload = make_challenge_payload(
        config.verify_method, config.verify_questions, lang=config.lang
    )
    if restore_permissions is not None:
        payload[RESTORE_PERMISSIONS_KEY] = serialize_permissions(restore_permissions)
    session_row = VerificationSession(
        chat_id=chat_id,
        user_id=user_id,
        method=config.verify_method,
        payload=payload,
        challenge_message_id=None,
        attempts_left=config.verify_max_attempts,
        expires_at=datetime.now(UTC) + timedelta(seconds=config.verify_timeout_seconds),
    )
    try:
        session_row = await database.create_verification_session(session_row)
    except Exception as e:
        logger.error(
            f"verify: failed to create session for {user_id} in {chat_id}: {e}"
        )
        return False

    if permissions is not None:
        try:
            await client.restrict_chat_member(chat_id, user_id, permissions)
        except Exception as e:
            logger.warning(f"verify: failed to restrict {user_id} in {chat_id}: {e}")
            await _cleanup_session(session_row)
            return False
    _register(session_row)

    challenge = None
    try:
        challenge = await _send_challenge(
            client,
            chat_id,
            session_row,
            config,
            config.lang,
            user_mention=await _user_mention(user),
        )
        session_row.challenge_message_id = challenge.id
        await database.update_verification_session(session_row)
    except Exception as e:
        logger.error(f"verify: failed to finish session {session_row.id}: {e}")
        if challenge is not None:
            try:
                await client.delete_messages(chat_id, challenge.id)
            except Exception as delete_error:
                logger.debug(
                    f"verify: failed to delete orphan challenge {session_row.id}: "
                    f"{delete_error}"
                )
        await restore_member_permissions(client, session_row)
        await _cleanup_session(session_row)
        return False
    return True


async def _test_verify_target(
    client: Client, message: pyrogram.types.Message
) -> pyrogram.types.User | pyrogram.types.Chat | None:
    """测试命令的目标: 回复对象(用户/频道) > 参数(id/用户名) > 命令发送者。"""
    reply = message.reply_to_message
    if reply is not None:
        if (
            reply.from_user is not None
            and reply.from_user.id != enums.ChatID.ANONYMOUS_ADMIN
        ):
            return reply.from_user
        if (
            reply.sender_chat is not None
            and reply.sender_chat.type == pyrogram.enums.ChatType.CHANNEL
        ):
            # 频道身份发言: 目标是该频道
            return reply.sender_chat
    command = message.command or []
    if len(command) > 1:
        raw = command[1].lstrip("@")
        try:
            user_id: int | str = int(raw)
        except ValueError:
            user_id = raw
        try:
            fetched = await client.get_users(user_id)
        except RPCError as e:
            logger.warning(f"verify: test target not found: {e}")
            return None
        if fetched is None:
            return None
        return fetched[0] if isinstance(fetched, list) else fetched
    return message.sender_chat or message.from_user


@Client.on_message(
    pyrogram.filters.command("testverify") & pyrogram.filters.group, group=0
)
async def test_verify_command(client: Client, message: pyrogram.types.Message) -> None:
    """调试命令: 仅 bot 全局管理员可用, 对目标成员立即触发一次完整验证。"""
    chat = message.chat
    if chat is None:
        return
    chat_id = chat.id
    if chat_id is None:
        return
    config = await _chat_config(chat_id)
    if config is None:
        return
    actor = message.sender_chat or message.from_user
    if actor is None or actor.id is None:
        return
    db_actor = await database.get_user_by_id(actor.id)
    if db_actor is None or not db_actor.is_bot_global_admin:
        await message.reply_text(
            i18n.t("bot.msg.no_permission_group", locale=config.lang)
        )
        return
    if not config.verify_enabled:
        await message.reply_text(
            i18n.t("bot.msg.verify.test_not_enabled", locale=config.lang)
        )
        return
    target = await _test_verify_target(client, message)
    if target is None:
        await message.reply_text(
            i18n.t("bot.msg.verify.test_user_not_found", locale=config.lang)
        )
        return
    target_id = target.id
    if target_id is None:
        return
    existing = _get_for(chat_id, target_id)
    if existing is not None:
        await _cleanup_session(existing)
    if not await _start_verification(client, chat_id, target, config):
        await message.reply_text(
            i18n.t("bot.msg.verify.test_verify_failed", locale=config.lang)
        )


@Client.on_message(pyrogram.filters.group, group=-50)
async def on_first_message_verify(
    client: Client, message: pyrogram.types.Message
) -> None:
    """首次用户消息触发验证并拦截未验证消息。"""
    chat = message.chat
    user = message.from_user
    if chat is None or user is None:
        return
    chat_id = chat.id
    if chat_id is None:
        return
    if client.me is not None and user.id == client.me.id:
        return
    if message.service:
        return  # 入群/退群等系统消息不触发验证
    text = message.text or message.caption or ""
    should_stop = await maybe_verify(
        client,
        VerifyContext(
            chat_id=chat_id,
            user=user,
            is_join=False,
            text=text,
        ),
    )
    if should_stop:
        message.stop_propagation()
