import pyrogram

from kmua import common, database, i18n
from kmua.common import ops
from kmua.common.utils import is_explicit_reply
from kmua.config import app_config

_RESULT_MESSAGE_KEYS = {
    ops.BotAdminResult.INVALID_TARGET: "bot.msg.botadmin.invalid_user",
    ops.BotAdminResult.TARGET_IS_UPSTREAM: "bot.msg.botadmin.target_is_upstream",
    ops.BotAdminResult.USER_NOT_FOUND: "bot.msg.botadmin.user_not_found",
    ops.BotAdminResult.USER_IS_BOT: "bot.msg.botadmin.user_is_bot",
    ops.BotAdminResult.USER_NOT_IN_CHAT: "bot.msg.botadmin.user_not_in_chat",
    ops.BotAdminResult.ALREADY_SET: "bot.msg.botadmin.already_set",
}


@pyrogram.Client.on_message(
    (pyrogram.filters.command("botpromote") | pyrogram.filters.command("botdemote"))
    & pyrogram.filters.group,
    group=0,
)
async def set_user_bot_admin_in_chat(
    client: pyrogram.Client, message: pyrogram.types.Message
):
    user = message.sender_chat or message.from_user
    chat = message.chat
    if not chat or not user:
        return
    chat_config = await database.get_chat_config(chat)
    if not await common.can_user_manage_bot_in_chat(user, chat):
        await message.reply(
            i18n.t("bot.msg.no_permission_group", locale=chat_config.lang)
        )
        return
    if not message.command:
        return
    try:
        reply_target = message.reply_to_message if is_explicit_reply(message) else None
        target_user_id = (
            (reply_target.sender_chat or reply_target.from_user).id  # type: ignore
            if reply_target
            else int(message.command[1])
            if (len(message.command) > 1 and message.command[1].isdigit())
            else None
        )
    except (ValueError, IndexError):
        await message.reply(
            i18n.t("bot.msg.botadmin.invalid_user", locale=chat_config.lang)
        )
        return
    if not target_user_id:
        await message.reply(
            i18n.t("bot.msg.botadmin.invalid_user", locale=chat_config.lang)
        )
        return

    demote = message.command[0] == "botdemote"
    db_actor = await database.get_user_by_id(user.id)
    actor_is_privileged = user.id in app_config.owners or bool(
        db_actor and db_actor.is_bot_global_admin
    )

    result = await ops.set_bot_admin(
        chat_id=chat.id,
        actor_id=user.id,
        target_id=target_user_id,
        promote=not demote,
        actor_is_privileged=actor_is_privileged,
    )
    if result is not ops.BotAdminResult.OK:
        await message.reply(
            i18n.t(_RESULT_MESSAGE_KEYS[result], locale=chat_config.lang)
        )
        return

    target = await database.get_user_by_id(target_user_id)
    await message.reply(
        i18n.t("bot.msg.botadmin.success", locale=chat_config.lang).format(
            user=target.full_name if target else target_user_id,
            status=not demote,
        )
    )
