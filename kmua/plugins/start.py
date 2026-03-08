import html

from pyrogram import enums, filters
from pyrogram.client import Client
from pyrogram.enums import ParseMode
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from kmua import common, consts, database, i18n
from kmua.common.memory_store import memttlcache
from kmua.logger import logger

_BOTTLE_MSG_PREFIX = "bottle_msg:"


class PrivateStartBotMarkup:
    def __init__(self, lang: str = "zh-CN") -> None:
        self.lang = lang

    def build(self) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        i18n.t("bot.button.repo", locale=self.lang),
                        url=consts.REPO_URL,
                    ),
                    InlineKeyboardButton(
                        i18n.t("bot.button.docs", locale=self.lang),
                        url=consts.DOCS_URL,
                    ),
                ],
                [
                    InlineKeyboardButton(
                        i18n.t("bot.button.user_waifu", locale=self.lang),
                        callback_data="user_waifu_manage",
                    ),
                    InlineKeyboardButton(
                        i18n.t("bot.button.user_quote", locale=self.lang),
                        callback_data="user_quote_manage",
                    ),
                ],
            ]
        )


@Client.on_message(filters.command("start") & filters.private, group=0)
async def start(client: Client, message: Message):
    user_config = await database.get_user_config(message.from_user)
    lang = user_config.lang
    if message.command is None:
        message.command = []
    if len(message.command) <= 1:
        await message.reply(
            text=i18n.t("bot.msg.private_start", locale=lang),
            reply_markup=PrivateStartBotMarkup(lang).build(),
        )
        return
    cmd = message.command[1]
    if cmd.startswith("inline_query"):
        await message.reply(
            text=i18n.t("bot.msg.help_inline", locale=lang).format(
                me_username=client.me.username
            )
        )
    elif cmd.startswith("seek_bottle"):
        if len(cmd.split("_")) != 3:
            await message.reply(
                text=i18n.t("bot.msg.private_start", locale=lang),
                reply_markup=PrivateStartBotMarkup(lang).build(),
            )
            return
        bottle_id = int(cmd.split("_")[2])
        bottle = await database.get_bottle_by_id(bottle_id)
        if bottle is None:
            await message.reply(
                text=i18n.t("bot.msg.bottle.not_found", locale=lang),
                reply_markup=PrivateStartBotMarkup(lang).build(),
            )
            return
        sender_user = await database.get_user_by_id(bottle.sender_id)
        sender_mention = await common.mention_html(sender_user)
        requester = await database.get_user_by_id(message.from_user.id)
        is_admin = requester is not None and requester.is_bot_global_admin
        if is_admin:
            seek_text = i18n.t(
                "bot.msg.bottle.seek_result_admin",
                locale=lang,
            ).format(
                sender=sender_mention,
                created_at=html.escape(bottle.created_at.strftime("%Y-%m-%d %H:%M:%S")),
                sender_id=bottle.sender_id,
            )
        else:
            seek_text = i18n.t(
                "bot.msg.bottle.seek_result",
                locale=lang,
            ).format(
                sender=sender_mention,
                created_at=html.escape(bottle.created_at.strftime("%Y-%m-%d %H:%M:%S")),
            )
        try:
            await message.reply(
                text=seek_text,
                parse_mode=ParseMode.HTML,
            )
        except Exception as e:
            logger.exception(e)
    elif cmd.startswith("view_bottle"):
        if len(cmd.split("_")) != 3:
            await message.reply(
                text=i18n.t("bot.msg.private_start", locale=lang),
                reply_markup=PrivateStartBotMarkup(lang).build(),
            )
            return
        bottle_id = int(cmd.split("_")[2])
        bottle = await database.get_bottle_by_id(bottle_id)
        if bottle is None:
            await message.reply(
                text=i18n.t("bot.msg.bottle.not_found", locale=lang),
                reply_markup=PrivateStartBotMarkup(lang).build(),
            )
            return
        bot_username = client.me.username if client.me else None
        buttons = [
            [
                InlineKeyboardButton(
                    i18n.t("bot.button.bottle.throw_back", locale=lang),
                    callback_data=f"throw_back {message.from_user.id}",
                ),
                InlineKeyboardButton(
                    i18n.t("bot.button.bottle.destroy", locale=lang),
                    callback_data=f"destroy_bottle {bottle.id} {message.from_user.id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    i18n.t("bot.button.bottle.report", locale=lang),
                    callback_data=f"report_bottle {bottle.id}",
                ),
                InlineKeyboardButton(
                    i18n.t("bot.button.bottle.seek", locale=lang),
                    url=f"https://t.me/{bot_username}?start=seek_bottle_{bottle.id}",
                )
                if bot_username
                else InlineKeyboardButton(
                    i18n.t("bot.button.bottle.seek", locale=lang),
                    callback_data="noop",
                ),
            ],
        ]
        reply_markup = InlineKeyboardMarkup(buttons)
        try:
            content_kwargs: dict = {"has_spoiler": True}
            if bottle.text:
                content_kwargs["caption"] = bottle.text
            bot_msg = None
            if bottle.media_type and bottle.file_id:
                match bottle.media_type:
                    case enums.MessageMediaType.PHOTO.name:
                        bot_msg = await message.reply_photo(
                            bottle.file_id,
                            reply_markup=reply_markup,
                            **content_kwargs,
                        )
                    case enums.MessageMediaType.VIDEO.name:
                        bot_msg = await message.reply_video(
                            bottle.file_id,
                            reply_markup=reply_markup,
                            **content_kwargs,
                        )
                    case enums.MessageMediaType.AUDIO.name:
                        bot_msg = await message.reply_audio(
                            bottle.file_id,
                            reply_markup=reply_markup,
                            **content_kwargs,
                        )
                    case enums.MessageMediaType.DOCUMENT.name:
                        bot_msg = await message.reply_document(
                            bottle.file_id,
                            reply_markup=reply_markup,
                            **content_kwargs,
                        )
                    case enums.MessageMediaType.ANIMATION.name:
                        bot_msg = await message.reply_animation(
                            bottle.file_id,
                            reply_markup=reply_markup,
                            **content_kwargs,
                        )
                    case _:
                        await message.reply(
                            text=i18n.t("bot.msg.bottle.unsupported_media", locale=lang)
                        )
            elif bottle.text:
                bot_msg = await message.reply_text(
                    bottle.text,
                    reply_markup=reply_markup,
                )
            if bot_msg:
                await memttlcache.set(
                    f"{_BOTTLE_MSG_PREFIX}{bot_msg.chat.id}:{bot_msg.id}",
                    {
                        "bottle_id": bottle.id,
                        "text": bottle.text,
                        "file_id": bottle.file_id,
                        "media_type": bottle.media_type,
                        "user_id": message.from_user.id,
                        "is_owner": True,
                        "lang": lang,
                    },
                    ttl=86400,
                )
        except Exception as e:
            logger.exception(e)
    else:
        await message.reply(
            text=i18n.t("bot.msg.private_start", locale=lang),
            reply_markup=PrivateStartBotMarkup(lang).build(),
        )


@Client.on_message(filters.command("start") & filters.group, group=0)
async def start_group(client: Client, message: Message):
    chat_config = await database.get_chat_config(message.chat)
    lang = chat_config.lang
    await message.reply(
        text=i18n.t("bot.msg.group_start", locale=lang),
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        i18n.t("bot.button.pm_me", locale=lang),
                        url=f"https://t.me/{client.me.username}?start=start",
                    )
                ]
            ]
        ),
    )


@Client.on_callback_query(filters.regex(r"^back_home"))
async def back_home(client: Client, callback_query: CallbackQuery):
    user_config = await database.get_user_config(callback_query.from_user)
    lang = user_config.lang
    try:
        await callback_query.message.edit(
            text=i18n.t("bot.msg.private_start", locale=lang),
            reply_markup=PrivateStartBotMarkup(lang).build(),
        )
    except Exception as e:
        logger.error(e)


@Client.on_callback_query(filters.regex(r"^delete_callback_query_message$"))
async def delete_callback_query_message(client: Client, callback_query: CallbackQuery):
    try:
        await callback_query.message.delete()
    except Exception as e:
        logger.error(f"Failed to delete message: {e.__class__.__name__} - {e}")
