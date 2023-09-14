from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, InputMediaPhoto
from telegram.ext import ContextTypes
from ..database import dao

from ..logger import logger
from ..common.user import get_big_avatar_bytes, get_small_avatar_bytes, get_user_info
from .jobs import reset_user_cd

_user_data_manage_markup = InlineKeyboardMarkup(
    [
        [
            InlineKeyboardButton("Refresh", callback_data="user_data_refresh"),
            InlineKeyboardButton("Back", callback_data="back_home"),
        ]
    ]
)


async def user_data_manage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    query = update.callback_query
    logger.info(f"[{chat.title}]({user.name}) <user data manage>")
    db_user = dao.get_user_by_id(user.id)
    info = get_user_info(user)
    if db_user.avatar_big_id:
        await query.edit_message_media(
            media=InputMediaPhoto(
                media=db_user.avatar_big_id,
                caption=info,
            ),
            reply_markup=_user_data_manage_markup,
        )
        return
    if db_user.avatar_big_blob:
        await query.edit_message_media(
            media=InputMediaPhoto(
                media=db_user.avatar_big_blob,
                caption=info,
            ),
            reply_markup=_user_data_manage_markup,
        )
        return
    await query.edit_message_caption(
        caption=info,
        reply_markup=_user_data_manage_markup,
    )


async def user_data_refresh(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    query = update.callback_query
    logger.info(f"[{chat.title}]({user.name}) <user data refresh>")

    if context.user_data.get("user_data_refresh_cd", False):
        await query.answer("技能冷却中...")
        return
    context.user_data["user_data_refresh_cd"] = True
    context.job_queue.run_once(
        callback=reset_user_cd,
        when=600,
        data={"cd_name": "user_data_refresh_cd"},
    )
    await query.answer("刷新中...")
    username = user.username
    full_name = user.full_name
    avatar_big_blog = await get_big_avatar_bytes(user.id, context)
    avatar_small_blog = await get_small_avatar_bytes(user.id, context)

    sent_message = await update.effective_chat.send_photo(
        photo=avatar_big_blog,
        caption="此消息用于获取头像缓存 id",
    )
    avatar_big_id = sent_message.photo[-1].file_id
    await sent_message.delete()
    db_user = dao.get_user_by_id(user.id)
    db_user.username = username
    db_user.full_name = full_name
    db_user.avatar_big_blob = avatar_big_blog
    db_user.avatar_small_blob = avatar_small_blog
    db_user.avatar_big_id = avatar_big_id
    dao.commit()
    info = get_user_info(user)
    await query.edit_message_media(
        media=InputMediaPhoto(
            media=avatar_big_id,
            caption=info,
        ),
        reply_markup=_user_data_manage_markup,
    )


async def user_waifu_manage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db_user = dao.add_user(update.effective_user)
    set_mention_text = "别@你" if db_user.waifu_mention else "抽到你时@你"
    waifu_manage_markup = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(text=set_mention_text, callback_data="set_mention")],
            [InlineKeyboardButton(text="返回", callback_data="back_home")],
        ]
    )
    text = f"""
当前设置:
是否@你: {db_user.waifu_mention}"""
    await update.callback_query.message.edit_caption(
        caption=text, reply_markup=waifu_manage_markup
    )
    dao.commit()


async def set_waifu_mention(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db_user = dao.add_user(update.effective_user)
    db_user.waifu_mention = not db_user.waifu_mention
    set_mention_text = "别@你" if db_user.waifu_mention else "抽到你时@你"
    waifu_manage_markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    text=set_mention_text, callback_data="set_waifu_mention"
                )
            ],
            [InlineKeyboardButton(text="返回", callback_data="back_home")],
        ]
    )
    text = f"""
当前设置:
是否@你: {db_user.waifu_mention}"""
    await update.callback_query.message.edit_caption(
        caption=text, reply_markup=waifu_manage_markup
    )
    dao.commit()
