import asyncio
import random

from telegram import Chat, Update, User
from telegram.constants import ChatAction
from telegram.ext import ContextTypes
from telegram.helpers import escape_markdown

from ..common.message import message_recorder
from ..common.user import (
    download_small_avatar,
    fake_users_id,
    mention_markdown_v2,
    verify_user_can_manage_bot_in_chat,
)
from ..common.waifu import (
    get_chat_waifu_relationships,
    get_marry_markup,
    get_waifu_text,
    render_waifu_graph,
    get_waifu_markup,
    get_remove_markup,
)
from ..dao.association import (
    delete_association_in_chat,
)
from ..dao.chat import (
    get_chat_users_without_bots_id,
)
from ..dao import db
from ..dao.user import (
    add_user,
    get_user_by_id,
)
from ..logger import logger
from ..models.models import ChatData, UserData
from ..service.user import (
    check_user_in_chat,
)
from ..service.waifu import (
    get_chat_married_users_id,
    get_chat_user_participated_waifu,
    get_user_waifu_in_chat,
    put_user_waifu_in_chat,
    refresh_user_all_waifu,
    refresh_user_waifu_in_chat,
)


async def waifu_graph(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(
        f"[{update.effective_chat.title}]({update.effective_user.name})"
        + f" {update.effective_message.text}"
    )
    if context.chat_data.get("waifu_graph_waiting", False):
        return
    if context.bot_data.get("refeshing_waifu_data", False):
        return

    msg_id = update.effective_message.id
    chat = update.effective_chat
    try:
        await send_waifu_graph(chat, context, msg_id)
    except Exception as e:
        logger.error(f"Error when generating waifu graph: {e}")
        await context.bot.send_message(
            chat.id,
            f"呜呜呜... kmua 被玩坏惹\n{e.__class__.__name__}: {e}",
            reply_to_message_id=msg_id,
        )
    finally:
        context.chat_data["waifu_graph_waiting"] = False


async def send_waifu_graph(
    chat: Chat | ChatData,
    context: ContextTypes.DEFAULT_TYPE,
    msg_id: int | None = None,
):
    logger.debug(f"Generating waifu graph for {chat.title}<{chat.id}>")
    relationships = get_chat_waifu_relationships(chat)
    participate_users = get_chat_user_participated_waifu(chat)
    if not participate_users or not relationships:
        await context.bot.send_message(
            chat.id,
            "本群今日没有人抽过老婆哦",
            reply_to_message_id=msg_id,
        )
        return

    status_msg = await context.bot.send_message(
        chat.id, "少女祈祷中...", reply_to_message_id=msg_id
    )

    user_info = {
        user.id: {
            "username": user.username or f"id: {user.id}",
            "avatar": user.avatar_small_blob,
        }
        for user in participate_users
    }
    image_bytes = render_waifu_graph(relationships, user_info)
    logger.debug(f"image_size: {len(image_bytes)}")
    await status_msg.delete()
    await context.bot.send_document(
        chat.id,
        document=image_bytes,
        caption=f"老婆关系图:\n {len(participate_users)} users",
        filename="waifu_graph.webp",
        disable_content_type_detection=True,
        reply_to_message_id=msg_id,
        allow_sending_without_reply=True,
    )
    logger.success(f"Send waifu graph for {chat.title}<{chat.id}>")


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
    if context.user_data.get("waifu_waiting", False):
        return
    context.user_data["waifu_waiting"] = True

    waifu: UserData = None
    message_recorder(update, context)
    try:
        await context.bot.send_chat_action(chat.id, ChatAction.TYPING)
        waifu, is_got_waifu = await _get_waifu_for_user(update, context, user, chat)
        if not waifu:
            return
        is_waifu_in_chat = check_user_in_chat(waifu, chat)
        if is_waifu_in_chat:
            put_user_waifu_in_chat(user, chat, waifu)
        waifu_markup = get_waifu_markup(waifu, user)
        text = get_waifu_text(waifu, is_got_waifu)
        if waifu.is_married:
            text = f"你和 [{escape_markdown(waifu.full_name,2)}](tg://user?id={waifu.id}) 已经结婚了哦, 还想娶第二遍嘛?"  # noqa: E501
            waifu_markup = None
            if is_waifu_in_chat:
                put_user_waifu_in_chat(waifu, chat, user)
        photo_to_send = await _get_photo_to_send(waifu, context)

        if photo_to_send is None:
            await update.message.reply_markdown_v2(
                text=text,
                reply_markup=waifu_markup,
                allow_sending_without_reply=True,
            )
            return
        try:
            sent_message = await update.message.reply_photo(
                photo=photo_to_send,
                caption=text,
                parse_mode="MarkdownV2",
                reply_markup=waifu_markup,
                allow_sending_without_reply=True,
            )
            avatar_big_id = sent_message.photo[0].file_id
            waifu.avatar_big_id = avatar_big_id
            logger.info(f"Bot: {text}")
        except Exception as e:
            logger.error(f"Can not send photo: {e.__class__.__name__}: {e}")
            await update.message.reply_markdown_v2(
                text=text,
                reply_markup=waifu_markup,
                allow_sending_without_reply=True,
            )
    finally:
        if waifu:
            if not waifu.avatar_small_blob:
                waifu.avatar_small_blob = await download_small_avatar(waifu.id, context)
        db_user = get_user_by_id(user.id)
        if not db_user.avatar_small_blob:
            db_user.avatar_small_blob = await download_small_avatar(user.id, context)
        db.commit()
        context.user_data["waifu_waiting"] = False


async def _get_waifu_for_user(
    update: Update, context: ContextTypes.DEFAULT_TYPE, user: User, chat: Chat
) -> (UserData | None, bool):
    """
    Get a waifu for user

    :return: (waifu, is_got_waifu)
    """
    if waifu := get_user_waifu_in_chat(user, chat):
        return waifu, True
    group_member = await _get_chat_members_id_to_get_waifu(update, context, user, chat)
    if not group_member:
        return None, False
    waifu_id = random.choice(group_member)
    while retry := 0 < 3:
        try:
            if waifu := get_user_by_id(waifu_id):
                return waifu, False
            else:
                waifu_chat = await context.bot.get_chat(waifu_id)
                waifu = add_user(waifu_chat)
                return waifu, False
        except Exception as e:
            logger.error(
                f"Can not get chat for {waifu_id}: {e.__class__.__name__}: {e}"
            )
            retry += 1
            waifu_id = random.choice(group_member)
            await asyncio.sleep(3)
    await update.message.reply_text(text="你没能抽到老婆, 稍后再试一次吧~")
    return None, False


async def _get_chat_members_id_to_get_waifu(
    update: Update, context: ContextTypes.DEFAULT_TYPE, user: User, chat: Chat
) -> list[int]:
    group_member = get_chat_users_without_bots_id(chat)
    married = get_chat_married_users_id(chat)
    to_remove = set(married + fake_users_id + [user.id])
    group_member = [i for i in group_member if i not in to_remove]
    if not group_member:
        await update.message.reply_text(text="你现在没有老婆, 因为咱的记录中找不到其他群友")  # noqa: E501
        return None
    return group_member


async def _get_photo_to_send(
    waifu: UserData, context: ContextTypes.DEFAULT_TYPE
) -> bytes | str | None:
    if waifu.avatar_big_id:
        return waifu.avatar_big_id
    if waifu.avatar_big_blob:
        return waifu.avatar_big_blob
    avatar = (await context.bot.get_chat(waifu.id)).photo
    if avatar:
        avatar = await (await avatar.get_big_file()).download_as_bytearray()
        avatar = bytes(avatar)
        waifu.avatar_big_blob = avatar
        return avatar


async def remove_waifu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query_data = update.callback_query.data
    if "confirm" in query_data:
        await _remove_waifu_confirm(update, context)
        return
    if "cancel" in query_data:
        await _remove_waifu_cancel(update, context)
        return
    query_data = query_data.split(" ")
    if not await verify_user_can_manage_bot_in_chat(
        update.effective_user, update.effective_chat, update, context
    ):
        return
    waifu_id = int(query_data[1])
    user_id = int(query_data[2])
    message = update.callback_query.message
    user = get_user_by_id(user_id)
    waifu = get_user_by_id(waifu_id)
    if not user or not waifu:
        await update.callback_query.answer(text="查无此人,可能已经被移除了")
        return
    markup = get_remove_markup(waifu, user)
    if message.photo:
        await message.edit_caption(caption="确定要移除ta吗?", reply_markup=markup)
        return
    await message.edit_text(text="确定要移除ta吗?", reply_markup=markup)


async def _remove_waifu_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await verify_user_can_manage_bot_in_chat(
        update.effective_user, update.effective_chat, update, context
    ):
        return
    query_data = update.callback_query.data.split(" ")
    waifu_id = int(query_data[1])
    user_id = int(query_data[2])
    message = update.callback_query.message
    user = get_user_by_id(user_id)
    waifu = get_user_by_id(waifu_id)
    if not user or not waifu:
        await update.callback_query.answer(text="查无此人,可能已经被移除了")
        return
    delete_association_in_chat(message.chat, waifu)
    refresh_user_waifu_in_chat(user, message.chat)
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
    if not await verify_user_can_manage_bot_in_chat(
        update.effective_user, update.effective_chat, update, context
    ):
        return
    query_data = update.callback_query.data.split(" ")
    waifu_id = int(query_data[1])
    user_id = int(query_data[2])
    message = update.callback_query.message
    user = get_user_by_id(user_id)
    waifu = get_user_by_id(waifu_id)
    text = get_waifu_text(waifu, False)
    markup = get_waifu_markup(waifu, user)
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
    db_waifu = get_user_by_id(waifu_id)
    db_user = get_user_by_id(user_id)
    message = query.message
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
    waifu_mention = mention_markdown_v2(db_waifu)
    user_mention = mention_markdown_v2(db_user)
    text = f"{waifu_mention}, 你愿意和 {user_mention} 结婚吗qwq?"
    reply_markup = get_marry_markup(waifu_id, user_id)
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


async def _agree_marry_waifu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    now_user = update.effective_user
    query = update.callback_query
    query_data = query.data.split(" ")
    waifu_id = int(query_data[1])
    user_id = int(query_data[2])
    db_waifu = get_user_by_id(waifu_id)
    db_user = get_user_by_id(user_id)
    message = query.message
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
    db.commit()
    db_user = get_user_by_id(user_id)
    db_waifu = get_user_by_id(waifu_id)
    refresh_user_all_waifu(db_user)
    refresh_user_all_waifu(db_waifu)
    put_user_waifu_in_chat(db_user, message.chat, db_waifu)
    put_user_waifu_in_chat(db_waifu, message.chat, db_user)
    waifu_mention = mention_markdown_v2(db_waifu)
    user_mention = mention_markdown_v2(db_user)
    text = f"恭喜 {waifu_mention} 和 {user_mention} 结婚啦\~"
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


async def _refuse_marry_waifu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    now_user = update.effective_user
    query = update.callback_query
    query_data = query.data.split(" ")
    waifu_id = int(query_data[1])
    db_waifu = get_user_by_id(waifu_id)
    message = query.message
    if now_user.id != waifu_id:
        await query.answer(
            text="(￣ε(#￣) 别人的事情咱不要打扰呢", show_alert=True, cache_time=60
        )  # noqa: E501
        return
    text = get_waifu_text(db_waifu, False)
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


async def _cancel_marry_waifu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    now_user = update.effective_user
    query = update.callback_query
    query_data = query.data.split(" ")
    waifu_id = int(query_data[1])
    user_id = int(query_data[2])
    message = query.message
    if now_user.id != user_id and now_user.id != waifu_id:
        await query.answer(
            text="(￣ε(#￣) 别人的事情咱不要打扰呢", show_alert=True, cache_time=60
        )  # noqa: E501
        return
    db_waifu = get_user_by_id(waifu_id)
    db_user = get_user_by_id(user_id)
    text = get_waifu_text(db_waifu, False)
    await query.answer(
        text="o((>ω< ))o 你取消了这个求婚请求",
        cache_time=5,
    )
    markup = get_waifu_markup(db_waifu, db_user)
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
