from telegram import (
    BotCommandScopeChat,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.ext import ContextTypes

from kmua import common, dao
from kmua.logger import logger
from kmua.models.models import ChatConfig


def _get_chat_config_reply_markup(chat_config: ChatConfig):
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    f"每日老婆 {"✔️" if chat_config.waifu_enabled else "❌"}",
                    callback_data="config_chat toggle waifu_enabled",
                ),
                InlineKeyboardButton(
                    f"删除事件消息 {"✔️" if chat_config.delete_events_enabled else "❌"}",
                    callback_data="config_chat toggle delete_events_enabled",
                ),
            ],
            [
                InlineKeyboardButton(
                    f"消息搜索 {"✔️" if chat_config.message_search_enabled else "❌"}",
                    callback_data="config_chat toggle message_search_enabled",
                ),
                InlineKeyboardButton(
                    f"语录置顶 {"✔️" if chat_config.quote_pin_message else "❌"}",
                    callback_data="config_chat toggle quote_pin_message",
                ),
            ],
            [
                InlineKeyboardButton(
                    f"AI回复 {"✔️" if chat_config.ai_reply else "❌"}",
                    callback_data="config_chat toggle ai_reply",
                ),
                InlineKeyboardButton(
                    f"随机涩图 {"✔️" if chat_config.setu_enabled else "❌"}",
                    callback_data="config_chat toggle setu_enabled",
                ),
            ],
            [
                InlineKeyboardButton(
                    f"解除频道置顶 {"✔️" if chat_config.unpin_channel_pin_enabled else "❌"}",
                    callback_data="config_chat toggle unpin_channel_pin_enabled",
                ),
            ],
            [
                InlineKeyboardButton("保存设置✅", callback_data="config_chat save"),
            ],
        ]
    )


async def config_chat_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    logger.info(f"[{chat.title}]({user.name}) <config_chat>")
    message = update.effective_message
    if not await common.verify_user_can_manage_bot_in_chat(user, chat, update, context):
        await message.reply_text(text="你没有权限哦")
    chat_config = dao.get_chat_config(chat)
    await message.reply_text(
        text="点击按钮修改群组设置哦\n",
        reply_markup=_get_chat_config_reply_markup(chat_config),
    )


async def config_chat_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    if not await common.verify_user_can_manage_bot_in_chat(user, chat, update, context):
        return
    logger.info(f"[{chat.title}]({user.name}) <config_chat_callback>")
    query = update.callback_query
    chat_config = dao.get_chat_config(chat)
    data = query.data.split(" ")
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
            case _:
                await query.answer("未知操作, 不可以干坏事哦")
                return
        dao.update_chat_config(chat, chat_config)
        await query.edit_message_reply_markup(
            reply_markup=_get_chat_config_reply_markup(chat_config)
        )
        return
    if data[1] == "save":
        await query.edit_message_text(
            text="群组配置已保存~",
            reply_markup=None,
        )
        commands = [
            ("start", "一键猫叫|召出菜单"),
            ("q", "记录语录"),
            ("d", "删除语录|管理群语录"),
            ("qrand", "随机语录"),
            ("t", "获取头衔|互赠头衔"),
            ("config", "更改群组设置"),
            ("help", "帮助|更多功能"),
        ]
        if chat_config.waifu_enabled:
            commands.insert(1, ("waifu", "今日老婆!"))
            commands.insert(2, ("waifu_graph", "老婆关系图！"))
        if chat_config.message_search_enabled:
            commands.insert(3, ("search", "搜索群消息"))
        if chat_config.setu_enabled:
            commands.insert(4, ("setu", "随机涩图"))
        await context.bot.set_my_commands(
            commands,
            scope=BotCommandScopeChat(chat_id=chat.id),
        )
        return
