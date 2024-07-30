import asyncio
import random

from telegram import Chat, Message, Update, User
from telegram.constants import ChatAction
from telegram.ext import ContextTypes
from telegram.helpers import escape_markdown

from kmua import common, dao
from kmua.logger import logger
from kmua.models.models import ChatData, UserData


async def switch_waifu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    message = update.effective_message
    logger.info(f"[{chat.title}]({user.name}) {message.text}")
    if not await common.verify_user_can_manage_bot_in_chat(user, chat, update, context):
        return
    disabled = dao.get_chat_waifu_disabled(chat)
    dao.update_chat_waifu_disabled(chat, not disabled)
    if disabled:
        await message.reply_text("已开启 waifu 功能")
    else:
        await message.reply_text("已关闭 waifu 功能")


async def waifu_graph(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(
        f"[{update.effective_chat.title}]({update.effective_user.name})"
        + f" {update.effective_message.text}"
    )
    if dao.get_chat_waifu_disabled(update.effective_chat):
        return
    if context.bot_data.get("cleaning_data", False):
        return

    msg_id = update.effective_message.id
    chat = update.effective_chat
    await asyncio.gather(
        update.effective_message.reply_text(random.choice(common.loading_word)),
        send_waifu_graph(chat, context, msg_id),
    )


async def send_waifu_graph(
    chat: Chat | ChatData,
    context: ContextTypes.DEFAULT_TYPE,
    msg_id: int | None = None,
):
    logger.debug(f"Generating waifu graph for {chat.title}<{chat.id}>")
    try:
        relationships = common.get_chat_waifu_relationships(chat)
        participate_users = dao.get_chat_user_participated_waifu(chat)
        if not participate_users or not relationships:
            if msg_id:
                await context.bot.send_message(
                    chat.id,
                    "本群今日没有人抽过老婆哦",
                    reply_to_message_id=msg_id,
                )
            return

        with open(common.DEFAULT_SMALL_AVATAR_PATH, "rb") as f:
            default_avatar = f.read()
        user_info = (
            {
                "id": user.id,
                "username": user.username or f"{user.id}",
                "avatar": user.avatar_small_blob or default_avatar,
            }
            for user in participate_users
        )
        image_bytes = common.render_waifu_graph(
            relationships, user_info, len(participate_users)
        )
        sent_message = await context.bot.send_document(
            chat.id,
            document=image_bytes,
            caption=f"老婆关系图:\n {len(participate_users)} users",
            filename="waifu_graph.webp",
            disable_content_type_detection=True,
            reply_to_message_id=msg_id,
            allow_sending_without_reply=True,
        )
        logger.success(
            f"Send waifu graph for {chat.title}<{chat.id}>, size: {sent_message.document.file_size}"
        )
    except Exception as err:
        error_info = f"{err.__class__.__name__}: {err}"
        logger.error(
            f"{error_info} happend when sending waifu graph for {chat.title}<{chat.id}>"
        )
        if msg_id:
            await context.bot.send_message(
                chat.id,
                f"呜呜呜, 画不出来了, {error_info}",
                reply_to_message_id=msg_id,
            )


async def today_waifu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    message = update.effective_message
    if message.sender_chat:
        user = message.sender_chat
    logger.info(
        f"[{chat.title}]({user.name if not message.sender_chat else user.title})"
        + f" {message.text}"
    )
    if dao.get_chat_waifu_disabled(chat):
        await message.reply_text("本群已禁用 waifu 功能")
        return
    if context.user_data.get("waifu_waiting", False):
        return
    context.user_data["waifu_waiting"] = True
    waifu: UserData = None
    try:
        await context.bot.send_chat_action(chat.id, ChatAction.TYPING)
        waifu, is_got_waifu = _get_waifu_for_user(user, chat)
        if not waifu:
            await message.reply_text("你现在没有老婆, 因为咱的记录中找不到其他群友")
            return
        if waifu.is_married and user.id != waifu.married_waifu_id:
            await message.reply_text("你没能抽到老婆, 再试一次吧~")
            return
        is_waifu_in_chat = dao.check_user_in_chat(waifu, chat)
        if is_waifu_in_chat:
            dao.put_user_waifu_in_chat(user, chat, waifu)
        waifu_markup = common.get_waifu_markup(waifu, user)
        text = common.get_waifu_text(waifu, is_got_waifu, user)
        if user.id == waifu.married_waifu_id:
            text = f"{common.mention_markdown_v2(user)}, 你和 {common.mention_markdown_v2(waifu)} 已经结婚了哦, 还想娶第二遍嘛?"
            waifu_markup = None
            if is_waifu_in_chat:
                dao.put_user_waifu_in_chat(waifu, chat, user)
        photo_to_send = await _get_photo_to_send(waifu, context)

        if photo_to_send is None:
            await message.reply_markdown_v2(
                text=text,
                reply_markup=waifu_markup,
            )
            return
        try:
            sent_message = await message.reply_photo(
                photo=photo_to_send,
                caption=text,
                parse_mode="MarkdownV2",
                reply_markup=waifu_markup,
            )
            avatar_big_id = sent_message.photo[0].file_id
            waifu.avatar_big_id = avatar_big_id
            logger.info(f"Bot: {text}")
        except Exception as e:
            logger.error(f"Can not send photo: {e.__class__.__name__}: {e}")
            await message.reply_markdown_v2(
                text=text,
                reply_markup=waifu_markup,
            )
    finally:
        if waifu:
            if not waifu.avatar_small_blob:
                waifu.avatar_small_blob = await common.download_small_avatar(
                    waifu.id, context
                )
        db_user = dao.get_user_by_id(user.id)
        if not db_user.avatar_small_blob:
            db_user.avatar_small_blob = await common.download_small_avatar(
                user.id, context
            )
        dao.commit()
        context.user_data["waifu_waiting"] = False


def _get_waifu_for_user(user: User, chat: Chat) -> tuple[UserData, bool]:
    """
    Get a waifu for user

    :return: (waifu, is_got_waifu)
    """
    if waifu := dao.get_user_waifu_in_chat(user, chat):
        return waifu, True
    return dao.take_waifu_for_user_in_chat(user, chat), False


async def _get_photo_to_send(
    waifu: UserData, context: ContextTypes.DEFAULT_TYPE
) -> bytes | str | None:
    if waifu.avatar_big_id:
        return waifu.avatar_big_id
    return await common.get_big_avatar_bytes(waifu.id, context)


async def remove_waifu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query_data = update.callback_query.data
    if "confirm" in query_data:
        await _remove_waifu_confirm(update, context)
        return
    if "cancel" in query_data:
        await _remove_waifu_cancel(update, context)
        return
    query_data = query_data.split(" ")
    if not await common.verify_user_can_manage_bot_in_chat(
        update.effective_user, update.effective_chat, update, context
    ):
        return
    waifu_id = int(query_data[1])
    user_id = int(query_data[2])
    message = update.callback_query.message
    if not message.is_accessible:
        return
    message: Message
    user = dao.get_user_by_id(user_id)
    waifu = dao.get_user_by_id(waifu_id)
    if not user or not waifu:
        await update.callback_query.answer(text="查无此人,可能已经被移除了")
        return
    markup = common.get_remove_markup(waifu, user)
    if message.photo:
        await message.edit_caption(caption="确定要移除ta吗?", reply_markup=markup)
        return
    await message.edit_text(text="确定要移除ta吗?", reply_markup=markup)


async def _remove_waifu_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await common.verify_user_can_manage_bot_in_chat(
        update.effective_user, update.effective_chat, update, context
    ):
        return
    query_data = update.callback_query.data.split(" ")
    waifu_id = int(query_data[1])
    user_id = int(query_data[2])
    message = update.callback_query.message
    if not message.is_accessible:
        return
    message: Message
    user = dao.get_user_by_id(user_id)
    waifu = dao.get_user_by_id(waifu_id)
    if not user or not waifu:
        await update.callback_query.answer(text="查无此人,可能已经被移除了")
        return
    dao.delete_association_in_chat(message.chat, waifu)
    dao.refresh_user_waifu_in_chat(user, message.chat)
    text = (
        f"_已移除该用户:_ {escape_markdown(waifu.full_name,2)}\n"
        + f"ta 曾是 {escape_markdown(user.full_name,2)} 的老婆"
    )
    if message.photo:
        await message.edit_caption(
            caption=text,
            parse_mode="MarkdownV2",
        )
        return
    await message.edit_text(text=text, parse_mode="MarkdownV2")


async def _remove_waifu_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await common.verify_user_can_manage_bot_in_chat(
        update.effective_user, update.effective_chat, update, context
    ):
        return
    query_data = update.callback_query.data.split(" ")
    waifu_id = int(query_data[1])
    user_id = int(query_data[2])
    message = update.callback_query.message
    if not message.is_accessible:
        return
    message: Message
    user = dao.get_user_by_id(user_id)
    waifu = dao.get_user_by_id(waifu_id)
    text = common.get_waifu_text(waifu, False, user)
    markup = common.get_waifu_markup(waifu, user)
    if message.photo:
        await message.edit_caption(
            caption=text,
            parse_mode="MarkdownV2",
            reply_markup=markup,
        )
        return
    await message.edit_text(
        text=text,
        parse_mode="MarkdownV2",
        reply_markup=markup,
    )


async def marry_waifu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if "agree" in query.data:
        await _agree_marry_waifu(update, context)
        return
    if "refuse" in query.data:
        await _refuse_marry_waifu(update, context)
        return
    if "cancel" in query.data:
        await _cancel_marry_waifu(update, context)
        return
    now_user = update.effective_user
    query_data = query.data.split(" ")
    waifu_id = int(query_data[1])
    user_id = int(query_data[2])
    db_waifu = dao.get_user_by_id(waifu_id)
    db_user = dao.get_user_by_id(user_id)
    message = query.message
    if not message.is_accessible:
        return
    message: Message
    if not db_waifu.is_real_user:
        await query.answer(
            text="＞﹏＜ Ta 不是真实用户哦.(不支持与匿名管理, 频道身份等结婚)",
            show_alert=True,
            cache_time=60,
        )
        return
    if now_user.id == waifu_id:
        await query.answer(
            text="(。・ω・。) 总会有人不远万里为你而来",
            show_alert=True,
            cache_time=60,
        )
        return
    if now_user.id != user_id:
        await query.answer(
            text="(￣ε(#￣) 别人的事情咱不要打扰呢", show_alert=True, cache_time=15
        )  # noqa: E501
        return
    if db_waifu.is_married:
        await query.answer(
            text="（＞人＜；）Ta 已经有别人了呢, 愿你找到对的人",
            show_alert=True,
            cache_time=60,
        )
        return
    waifu_mention = common.mention_markdown_v2(db_waifu)
    user_mention = common.mention_markdown_v2(db_user)
    text = f"{waifu_mention}, 你愿意和 {user_mention} 结婚吗qwq?"
    reply_markup = common.get_marry_markup(waifu_id, user_id)
    if message.photo:
        await message.edit_caption(
            caption=text,
            reply_markup=reply_markup,
            parse_mode="MarkdownV2",
        )
        return
    await message.edit_text(
        text=text,
        reply_markup=reply_markup,
        parse_mode="MarkdownV2",
    )


async def _agree_marry_waifu(update: Update, _: ContextTypes.DEFAULT_TYPE):
    now_user = update.effective_user
    query = update.callback_query
    query_data = query.data.split(" ")
    waifu_id = int(query_data[1])
    user_id = int(query_data[2])
    db_waifu = dao.get_user_by_id(waifu_id)
    db_user = dao.get_user_by_id(user_id)
    message = query.message
    if not message.is_accessible:
        return
    message: Message
    if now_user.id != waifu_id:
        await query.answer(
            text="(￣ε(#￣) 别人的事情咱不要打扰呢", show_alert=True, cache_time=60
        )  # noqa: E501
        return
    if db_waifu.is_married or db_user.is_married:
        await query.answer(
            text="（＞人＜；）Ta 已经有别人了呢, 愿你找到对的人",
            show_alert=True,
            cache_time=60,
        )
        return
    db_user.married_waifu_id = waifu_id
    db_user.is_married = True
    db_waifu.married_waifu_id = user_id
    db_waifu.is_married = True
    dao.commit()
    db_user = dao.get_user_by_id(user_id)
    db_waifu = dao.get_user_by_id(waifu_id)
    dao.refresh_user_all_waifu(db_user)
    dao.refresh_user_all_waifu(db_waifu)
    dao.put_user_waifu_in_chat(db_user, message.chat, db_waifu)
    dao.put_user_waifu_in_chat(db_waifu, message.chat, db_user)
    waifu_mention = common.mention_markdown_v2(db_waifu)
    user_mention = common.mention_markdown_v2(db_user)
    text = rf"恭喜 {waifu_mention} 和 {user_mention} 结婚啦\~"
    if message.photo:
        await message.edit_caption(
            caption=text,
            parse_mode="MarkdownV2",
        )
        return
    await message.edit_text(
        text=text,
        parse_mode="MarkdownV2",
    )


async def _refuse_marry_waifu(update: Update, _: ContextTypes.DEFAULT_TYPE):
    now_user = update.effective_user
    query = update.callback_query
    query_data = query.data.split(" ")
    waifu_id = int(query_data[1])
    db_waifu = dao.get_user_by_id(waifu_id)
    message = query.message
    if not message.is_accessible:
        return
    message: Message
    if now_user.id != waifu_id:
        await query.answer(
            text="(￣ε(#￣) 别人的事情咱不要打扰呢", show_alert=True, cache_time=60
        )  # noqa: E501
        return
    text = common.get_waifu_text(db_waifu, False)
    await query.answer(
        text="(´。＿。｀) 你拒绝了 ta 的求婚呢. 有些人一旦错过就不再...",
        show_alert=True,
        cache_time=60,
    )
    if message.photo:
        await message.edit_caption(
            caption=text,
            parse_mode="MarkdownV2",
        )
        return
    await message.edit_text(
        text=text,
        parse_mode="MarkdownV2",
    )


async def _cancel_marry_waifu(update: Update, _: ContextTypes.DEFAULT_TYPE):
    now_user = update.effective_user
    query = update.callback_query
    query_data = query.data.split(" ")
    waifu_id = int(query_data[1])
    user_id = int(query_data[2])
    message = query.message
    if not message.is_accessible:
        return
    message: Message
    if now_user.id not in (waifu_id, user_id):
        await query.answer(
            text="(￣ε(#￣) 别人的事情咱不要打扰呢",
            show_alert=True,
            cache_time=60,
        )
        return
    db_waifu = dao.get_user_by_id(waifu_id)
    db_user = dao.get_user_by_id(user_id)
    text = common.get_waifu_text(db_waifu, False, db_user)
    await query.answer(
        text="o((>ω< ))o 你取消了这个求婚请求",
        cache_time=5,
    )
    markup = common.get_waifu_markup(db_waifu, db_user)
    if message.photo:
        await message.edit_caption(
            caption=text,
            parse_mode="MarkdownV2",
            reply_markup=markup,
        )
        return
    await message.edit_text(
        text=text,
        parse_mode="MarkdownV2",
        reply_markup=markup,
    )
