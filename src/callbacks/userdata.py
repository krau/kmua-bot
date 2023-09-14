from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, InputMediaPhoto
from telegram.ext import ContextTypes
from ..database import dao

from ..logger import logger
from ..common.user import get_big_avatar_bytes, get_small_avatar_bytes, get_user_info
from ..common.waifu import get_user_waifu_info
from ..common.utils import back_home_markup
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
    avatar_big_id = None
    if avatar_big_blog:
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
    if avatar_big_id:
        await query.edit_message_media(
            media=InputMediaPhoto(
                media=avatar_big_id,
                caption=info,
            ),
            reply_markup=_user_data_manage_markup,
        )
        return
    await query.edit_message_caption(
        caption=info,
        reply_markup=_user_data_manage_markup,
    )


async def user_waifu_manage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    query_data = query.data
    if "divorce" in query_data:
        await _divorce_ask(update, context)
        return
    db_user = dao.get_user_by_id(update.effective_user.id)
    if "set_waifu_mention" in query_data:
        db_user.waifu_mention = not db_user.waifu_mention
    set_mention_text = "别@你" if db_user.waifu_mention else "抽到你时@你"
    waifu_manage_markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    text=set_mention_text, callback_data="set_waifu_mention"
                ),
                InlineKeyboardButton(text="离婚", callback_data="divorce"),
            ],
            [InlineKeyboardButton(text="返回", callback_data="back_home")],
        ]
    )
    text = get_user_waifu_info(update.effective_user)
    if query.message.photo:
        await query.edit_message_caption(caption=text, reply_markup=waifu_manage_markup)
    else:
        await query.edit_message_text(text=text, reply_markup=waifu_manage_markup)
    dao.commit()


_divorce_ask_markup = InlineKeyboardMarkup(
    [
        [
            InlineKeyboardButton(text="离婚", callback_data="divorce_confirm"),
            InlineKeyboardButton(text="算了", callback_data="back_home"),
        ]
    ]
)


async def _divorce_ask(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if "divorce_confirm" in query.data:
        await _divorce_confirm(update, context)
        return
    db_user = dao.get_user_by_id(update.effective_user.id)
    if not db_user.is_married:
        await query.answer("可是...你还没有结婚呀qwq", show_alert=True, cache_time=15)
        return
    married_waifu = dao.get_user_by_id(db_user.married_waifu_id)

    if query.message.photo and married_waifu.avatar_big_id:
        await query.edit_message_media(
            media=InputMediaPhoto(
                media=married_waifu.avatar_big_id,
                caption=f"你确定要和 {married_waifu.full_name} 离婚吗?",
            ),
            reply_markup=_divorce_ask_markup,
        )
        return
    await query.edit_message_caption(
        caption=f"你确定要和 {married_waifu.full_name} 离婚吗?",
        reply_markup=_divorce_ask_markup,
    )


async def _divorce_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db_user = dao.get_user_by_id(update.effective_user.id)
    query = update.callback_query
    married_waifu = dao.get_user_by_id(db_user.married_waifu_id)
    db_user.is_married = False
    db_user.married_waifu_id = None
    married_waifu.is_married = False
    married_waifu.married_waifu_id = None
    dao.commit()
    dao.refresh_user_all_waifu(db_user)
    dao.refresh_user_all_waifu(married_waifu)
    await query.edit_message_caption(
        caption="**愿你有一天和重要之人重逢**",
        parse_mode="MarkdownV2",
        reply_markup=back_home_markup,
    )
