from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from kmua import common, dao
from kmua.logger import logger
from kmua.config import settings

_start_bot_markup = InlineKeyboardMarkup(
    [
        [
            InlineKeyboardButton("开源仓库", url=common.OPEN_SOURCE_URL),
            InlineKeyboardButton("详细帮助", url=common.DETAIL_HELP_URL),
        ],
        [
            InlineKeyboardButton("个人信息", callback_data="user_data_manage"),
            InlineKeyboardButton("语录管理", callback_data="user_quote_manage"),
        ],
        [
            InlineKeyboardButton("老婆管理", callback_data="user_waifu_manage"),
            InlineKeyboardButton("喵喵喵喵", callback_data="noop"),
        ],
    ]
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"[{update.effective_user.name}] <start>")
    if update.effective_chat.type != "private":
        if update.effective_message.text == "/start":
            # 如果是群聊，且没有艾特，直接返回
            return
        await _start_in_group(update, context)
        return

    if update.callback_query:
        if update.callback_query.message.photo:
            await update.callback_query.edit_message_caption(
                caption="Nya~",
                reply_markup=_start_bot_markup,
            )
            return
        await update.callback_query.delete_message()
    db_bot_user = dao.get_user_by_id(context.bot.id)
    if not db_bot_user:
        db_bot_user = dao.add_user((await context.bot.get_me()))
        db_bot_user.avatar_big_blob = await common.download_big_avatar(
            context.bot.id, context
        )
        dao.commit()
    photo = db_bot_user.avatar_big_id or db_bot_user.avatar_big_blob
    sent_message = await update.effective_message.reply_photo(
        photo=photo,
        caption="Nya~",
        reply_markup=_start_bot_markup,
    )
    db_bot_user.avatar_big_id = sent_message.photo[-1].file_id
    dao.commit()
    if update.effective_user.id in settings.owners:
        dao.update_user_is_bot_global_admin(update.effective_user, True)


async def _start_in_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"[{update.effective_user.name}] <start in group>")
    start_bot_markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "PM me nya~", url=f"https://t.me/{context.bot.username}?start=start"
                )
            ],
            [
                InlineKeyboardButton("Open source", url=common.OPEN_SOURCE_URL),
                InlineKeyboardButton("Detail help", url=common.DETAIL_HELP_URL),
            ],
        ]
    )
    sent_message = await update.effective_message.reply_text(
        text="Nya!",
        reply_markup=start_bot_markup,
    )
    logger.info(f"Bot:{sent_message.text}")
