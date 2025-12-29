import pyrogram
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from kmua import common, database
from kmua.database.models import ChatConfig
from kmua.i18n import i18n


class ChatConfigMarkup:
    def __init__(self, chat_config: ChatConfig, lang: str = "zh-CN"):
        self.chat_config = chat_config
        self.lang = lang

    def get_status_emoji(self, boolean: bool):
        if boolean:
            return "✔️"
        return "❌"

    def get_callback_data(self, key: str):
        return f"config_chat toggle {key}"

    def build(self):
        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        f"{i18n.t('bot.button.chat_config.waifu', locale=self.lang)} {self.get_status_emoji(self.chat_config.waifu_enabled)}",
                        callback_data=self.get_callback_data("waifu_enabled"),
                    ),
                    InlineKeyboardButton(
                        f"{i18n.t('bot.button.chat_config.delete_events', locale=self.lang)} {self.get_status_emoji(self.chat_config.delete_events_enabled)}",
                        callback_data=self.get_callback_data("delete_events_enabled"),
                    ),
                    InlineKeyboardButton(
                        f"{i18n.t('bot.button.chat_config.quote_pin_message', locale=self.lang)} {self.get_status_emoji(self.chat_config.quote_pin_message)}",
                        callback_data=self.get_callback_data("quote_pin_message"),
                    ),
                ],
                [
                    InlineKeyboardButton(
                        f"{i18n.t('bot.button.chat_config.ai_reply', locale=self.lang)} {self.get_status_emoji(self.chat_config.ai_reply)}",
                        callback_data=self.get_callback_data("ai_reply"),
                    ),
                    InlineKeyboardButton(
                        f"{i18n.t('bot.button.chat_config.ai_comment', locale=self.lang)} {self.get_status_emoji(self.chat_config.ai_comment)}",
                        callback_data=self.get_callback_data("ai_comment"),
                    ),
                    InlineKeyboardButton(
                        f"{i18n.t('bot.button.chat_config.setu_enabled', locale=self.lang)} {self.get_status_emoji(self.chat_config.setu_enabled)}",
                        callback_data=self.get_callback_data("setu_enabled"),
                    ),
                ],
                [
                    InlineKeyboardButton(
                        f"{i18n.t('bot.button.chat_config.unpin_channel_pin_enabled', locale=self.lang)} {self.get_status_emoji(self.chat_config.unpin_channel_pin_enabled)}",
                        callback_data=self.get_callback_data(
                            "unpin_channel_pin_enabled"
                        ),
                    ),
                    InlineKeyboardButton(
                        f"{i18n.t('bot.button.chat_config.convert_b23_enabled', locale=self.lang)} {self.get_status_emoji(self.chat_config.convert_b23_enabled)}",
                        callback_data=self.get_callback_data("convert_b23_enabled"),
                    ),
                ],
                [
                    InlineKeyboardButton(
                        f"{i18n.t('bot.button.chat_config.parse_artwork_enabled', locale=self.lang)} {self.get_status_emoji(self.chat_config.parse_artwork_enabled)}",
                        callback_data=self.get_callback_data("parse_artwork_enabled"),
                    ),
                    InlineKeyboardButton(
                        f"{i18n.t('bot.button.chat_config.pick_bottle_enabled', locale=self.lang)} {self.get_status_emoji(self.chat_config.pick_bottle_enabled)}",
                        callback_data=self.get_callback_data("pick_bottle_enabled"),
                    ),
                ],
                [
                    InlineKeyboardButton(
                        i18n.t("bot.button.chat_config.save", locale=self.lang),
                        callback_data="config_chat save",
                    ),
                ],
            ]
        )


@pyrogram.Client.on_message(
    pyrogram.filters.command("config") & pyrogram.filters.group, group=0
)
async def config_chat_cmd(client: pyrogram.Client, message: pyrogram.types.Message):
    user = message.sender_chat or message.from_user
    chat = message.chat
    if not await common.can_user_manage_bot_in_chat(user, chat):
        chat_config = await database.get_chat_config(chat)
        lang = chat_config.lang
        await message.reply(
            text=i18n.t("bot.msg.no_permission_group", locale=lang),
        )
        return
    chat_config = await database.get_chat_config(chat)
    lang = chat_config.lang
    await message.reply(
        text=i18n.t("bot.msg.group_config", locale=lang),
        reply_markup=ChatConfigMarkup(chat_config, lang).build(),
    )


@pyrogram.Client.on_callback_query(pyrogram.filters.regex("^config_chat"), group=0)
async def config_chat(
    client: pyrogram.Client, callback_query: pyrogram.types.CallbackQuery
):
    chat = callback_query.message.chat
    user = callback_query.from_user
    if not await common.can_user_manage_bot_in_chat(user, chat):
        user_config = await database.get_user_config(user)
        await callback_query.answer(
            text=i18n.t("bot.msg.no_permission_group", locale=user_config.lang),
            show_alert=True,
            cache_time=10,
        )
        return
    chat_config = await database.get_chat_config(chat)
    lang = chat_config.lang
    data = str(callback_query.data).split(" ")
    if data[1] == "toggle":
        match data[2]:
            case "waifu_enabled":
                chat_config.waifu_enabled = not chat_config.waifu_enabled
            case "delete_events_enabled":
                chat_config.delete_events_enabled = (
                    not chat_config.delete_events_enabled
                )
            case "unpin_channel_pin_enabled":
                chat_config.unpin_channel_pin_enabled = (
                    not chat_config.unpin_channel_pin_enabled
                )
            case "message_search_enabled":
                chat_config.message_search_enabled = (
                    not chat_config.message_search_enabled
                )
            case "quote_pin_message":
                chat_config.quote_pin_message = not chat_config.quote_pin_message
            case "ai_reply":
                chat_config.ai_reply = not chat_config.ai_reply
            case "setu_enabled":
                chat_config.setu_enabled = not chat_config.setu_enabled
            case "convert_b23_enabled":
                chat_config.convert_b23_enabled = not chat_config.convert_b23_enabled
            case "parse_artwork_enabled":
                chat_config.parse_artwork_enabled = (
                    not chat_config.parse_artwork_enabled
                )
            case "pick_bottle_enabled":
                chat_config.pick_bottle_enabled = not chat_config.pick_bottle_enabled
            case "ai_comment":
                chat_config.ai_comment = not chat_config.ai_comment
            case _:
                await callback_query.answer(
                    text=i18n.t("bot.msg.unknown_operation", locale=lang),
                )
                return
        chat_config = await database.update_chat_config(chat, chat_config)
        await callback_query.edit_message_reply_markup(
            ChatConfigMarkup(chat_config, lang).build()
        )
        return
    if data[1] == "save":
        await callback_query.edit_message_text(
            text=i18n.t("bot.msg.group_config_saved", locale=lang),
            reply_markup=None,
        )
        return
