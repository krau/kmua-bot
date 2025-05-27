import io

import pyrogram

from kmua import common, database, i18n


def _lock_key(user_id: int) -> str:
    return f"user_refresh_avatar:{user_id}"


@pyrogram.Client.on_message(pyrogram.filters.command("f5avatar"), group=0)
async def refresh_user_avatar(client: pyrogram.Client, message: pyrogram.types.Message):
    user = message.sender_chat or message.from_user
    if await common.memttlcache.get(_lock_key(user.id)):
        return
    db_user = await database.get_user_by_id(user.id)
    if not db_user:
        return
    await common.memttlcache.set(_lock_key(user.id), True)
    refreshing_msg = await message.reply_text(
        i18n.t("bot.msg.refreshing_avatar", locale=db_user.user_config.lang)
    )
    avatar = common.ChatAvatar(user.id)
    ok = await avatar.force_refresh()
    if not ok:
        await message.reply_text(
            i18n.t("bot.msg.refresh_failed", locale=db_user.user_config.lang)
        )
        return
    avatar_big = await avatar.get_bytes()
    if not avatar_big:
        await message.reply_text(
            i18n.t("bot.msg.refresh_failed", locale=db_user.user_config.lang)
        )
        return
    msg = await refreshing_msg.edit_media(
        media=pyrogram.types.InputMediaPhoto(
            media=io.BytesIO(avatar_big),
        )
    )
    if not msg:
        await message.reply_text(
            i18n.t("bot.msg.refresh_failed", locale=db_user.user_config.lang)
        )
        return
    await database.update_user_avatar(db_user.id, msg.photo.file_id)
    await msg.edit_text(
        i18n.t("bot.msg.refresh_success", locale=db_user.user_config.lang)
    )
