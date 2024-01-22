from math import ceil

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, Update
from telegram.ext import ContextTypes
from telegram.helpers import escape_markdown

from kmua import common, dao
from kmua.logger import logger

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
    query = update.callback_query
    logger.info(f"({user.name}) <user data manage>")
    db_user = dao.get_user_by_id(user.id)
    info = common.get_user_info(user)
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
    query = update.callback_query
    logger.info(f"({user.name}) <user data refresh>")

    if context.bot_data.get(user.id, {}).get("user_data_refresh_cd", False):
        await query.answer("技能冷却中...", cache_time=60)
        return
    if not context.bot_data.get(user.id, {}):
        context.bot_data[user.id] = {}
    context.bot_data[user.id]["user_data_refresh_cd"] = True

    context.job_queue.run_once(
        callback=reset_user_cd,
        when=600,
        data={"cd_name": "user_data_refresh_cd"},
        user_id=user.id,
    )
    await query.answer("刷新中...")
    context.application.drop_user_data(user.id)
    username = user.username
    full_name = user.full_name
    avatar_big_blog = await common.download_big_avatar(user.id, context)
    avatar_small_blog = await common.download_small_avatar(user.id, context)
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
    info = common.get_user_info(user)
    info += "\n刷新成功"
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
    text = common.get_user_waifu_info(update.effective_user)
    await query.edit_message_caption(caption=text, reply_markup=waifu_manage_markup)
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
        caption="_愿你有一天和重要之人重逢_",
        parse_mode="MarkdownV2",
        reply_markup=common.back_home_markup,
    )
    logger.debug(
        f"{db_user.full_name}<{db_user.id}> divorced {married_waifu.full_name}<{married_waifu.id}>"  # noqa: E501
    )


async def delete_user_quote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if "user_quote_manage" in query.data:
        await _user_quote_manage(update, context)
        return
    if "qer_quote_manage" in query.data:
        await _qer_quote_manage(update, context)
        return
    quote_link = query.data.split(" ")[1]
    dao.delete_quote_by_link(quote_link)
    await query.answer("已删除", show_alert=False, cache_time=5)
    await _user_quote_manage(update, context)


async def _user_quote_manage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    query = update.callback_query
    logger.info(f"({user.name}) <user quote manage>")
    page = int(query.data.split(" ")[-1]) if len(query.data.split(" ")) > 1 else 1
    page_size = 5
    quotes_count = dao.get_user_quotes_count(user)
    max_page = ceil(quotes_count / page_size)
    if quotes_count == 0:
        caption = (
            "已经没有语录啦" if "delete_user_quote" in query.data else "你没有语录呢"
        )  # noqa: E501
        await query.edit_message_caption(
            caption=caption,
            reply_markup=common.no_quote_markup,
        )
        return
    if page > max_page or page < 1:
        await update.callback_query.answer("已经没有啦", show_alert=False, cache_time=5)
        return
    text = f"你的语录: 共{quotes_count}条; 第{page}/{max_page}页\n"
    text += "点击序号删除语录\n\n"
    quotes = dao.get_user_quotes_page(user, page, page_size)
    keyboard, line = [], []
    for index, quote in enumerate(quotes):
        quote_content = (
            escape_markdown(quote.text[:100], 2)
            if quote.text
            else "A non\-text message"
        )
        text += f"{index + 1}\. [{quote_content}]({escape_markdown(quote.link,2)})\n\n"

        line.append(
            InlineKeyboardButton(
                text=f"{index + 1}",
                callback_data=f"delete_user_quote {quote.link} {str(page)}",
            )
        )
    keyboard.append(line)
    keyboard.append(common.qer_quote_manage_button)
    keyboard.append(common.get_user_quote_navigation_buttons(page))
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_caption(
        caption=text,
        parse_mode="MarkdownV2",
        reply_markup=reply_markup,
    )


async def _qer_quote_manage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    query = update.callback_query
    logger.info(f"({user.name}) <qer quote manage>")
    page = int(query.data.split(" ")[-1]) if len(query.data.split(" ")) > 1 else 1
    page_size = 5
    quotes_count = dao.get_qer_quotes_count(user)
    max_page = ceil(quotes_count / page_size)
    if quotes_count == 0:
        await query.edit_message_caption(
            caption="这里空空如也",
            reply_markup=common.back_home_markup,
        )
        return
    if page > max_page or page < 1:
        await update.callback_query.answer("已经没有啦", show_alert=False, cache_time=5)
        return
    text = f"被你q过的语录: 共{quotes_count}条; 第{page}/{max_page}页\n"
    quotes = dao.get_qer_quotes_page(user, page, page_size)
    for index, quote in enumerate(quotes):
        quote_content = (
            escape_markdown(quote.text[:100], 2)
            if quote.text
            else "A non\-text message"
        )
        text += f"{index + 1}\. [{quote_content}]({escape_markdown(quote.link,2)})\n\n"
    keyboard = []
    keyboard.append(common.get_qer_quote_navigation_buttons(page))
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_caption(
        caption=text,
        parse_mode="MarkdownV2",
        reply_markup=reply_markup,
    )
