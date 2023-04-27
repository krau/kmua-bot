import random
import time
from datetime import datetime
from uuid import uuid1, uuid4

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQueryResultArticle,
    InlineQueryResultCachedPhoto,
    InputTextMessageContent,
    Update,
)
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from .config.config import settings
from .logger import logger
from .model import ImgQuote, MemberData, TextQuote
from .utils import generate_quote_img, message_recorder, random_unit, sort_topn_bykey


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(
        f"[{update.effective_chat.title}]({update.effective_user.name})"
        + f" {update.effective_message.text}"
    )
    await message_recorder(update, context)
    if update.effective_chat.type != "private":
        if update.effective_message.text == "/start":
            # 如果是群聊，且没有艾特，直接返回
            return
        await _start_in_group(update, context)
        return
    start_bot_markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "拉我进群", url=f"https://t.me/{context.bot.username}?startgroup=new"
                ),
                InlineKeyboardButton("开源主页", url="https://github.com/krau/kmua-bot"),
            ],
            [InlineKeyboardButton("你的数据", callback_data="user_data_manage")],
        ]
    )
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="喵喵喵?",
        reply_markup=start_bot_markup,
    )


async def _start_in_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(
        f"[{update.effective_chat.title}]({update.effective_user.name})"
        + f" {update.effective_message.text}"
    )
    start_bot_markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "私聊Kmua", url=f"https://t.me/{context.bot.username}?start=start"
                )
            ]
        ]
    )
    sent_message = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="喵喵喵?",
        reply_markup=start_bot_markup,
    )
    logger.info(f"Bot:{sent_message.text}")
    await context.bot.send_sticker(
        chat_id=update.effective_chat.id,
        sticker="CAACAgEAAxkBAAIKWGREi3q4O_H40T66DbTZGyNAf0CbAALPAAN92oBFKGj8op00zJ8vBA",
    )


async def chat_migration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.trace(
        f"[{update.effective_chat.title}]({update.effective_user.name})"
        + "<chat_migration>"
    )
    message = update.message
    application = context.application
    application.migrate_chat_data(message=message)


async def title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(
        f"[{update.effective_chat.title}]({update.effective_user.name})"
        + f" {update.effective_message.text}"
    )
    await message_recorder(update, context)
    if update.effective_chat.type == "private":
        sent_message = await context.bot.send_message(
            chat_id=update.effective_chat.id, text="请在群聊中使用哦"
        )
        logger.info(f"Bot: {sent_message.text}")
        return
    this_user = update.effective_user
    this_message = update.effective_message
    replied_user = None
    replied_message = None
    bot_username = context.bot_data["bot_username"]
    custom_title = update.effective_message.text[3:]
    user_id = this_user.id
    if bot_username in this_message.text:
        custom_title = custom_title.replace(bot_username, "")[1:]
    if update.effective_message.reply_to_message:
        replied_message = update.effective_message.reply_to_message
        replied_user = replied_message.from_user
        user_id = replied_user.id
        if not custom_title:
            custom_title = (
                replied_user.username
                if replied_user.username
                else replied_user.full_name
            )
    if not custom_title:
        custom_title = this_user.username if this_user.username else this_user.full_name
    try:
        await context.bot.promote_chat_member(
            chat_id=update.effective_chat.id,
            user_id=user_id,
            can_manage_chat=True,
            can_change_info=True,
            can_manage_video_chats=True,
            can_pin_messages=True,
            can_invite_users=True,
        )
        await context.bot.set_chat_administrator_custom_title(
            chat_id=update.effective_chat.id,
            user_id=user_id,
            custom_title=custom_title,
        )
        if replied_message:
            text_when_have_replied_message = f"""
            [{this_user.full_name}](tg://user?id={this_user.id})把[{replied_user.full_name}](tg://user?id={replied_user.id})变成{custom_title}!
            """
        text = (
            f"好, 你现在是{custom_title}啦"
            if not replied_message
            else text_when_have_replied_message
        )
        sent_message = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            reply_to_message_id=update.effective_message.id,
            text=text,
            parse_mode="Markdown",
        )
        logger.info(f"Bot: {sent_message.text}")
    except BadRequest:
        sent_message = await context.bot.send_message(
            chat_id=update.effective_chat.id, text="Kmua没有足够的权限"
        )
        logger.info(f"Bot: {sent_message.text}")
    except Exception as e:
        await context.bot.send_message(
            chat_id=update.effective_chat.id, text=f"{e.__class__.__name__}: {e}"
        )
        logger.error(f"{e.__class__.__name__}: {e}")


async def quote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(
        f"[{update.effective_chat.title}]({update.effective_user.name})"
        + f" {update.effective_message.text}"
    )
    await message_recorder(update, context)
    if not update.effective_message.reply_to_message:
        sent_message = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            reply_to_message_id=update.effective_message.id,
            text="请回复一条消息",
        )
        logger.info(f"Bot: {sent_message.text}")
        return
    quote_message = update.effective_message.reply_to_message
    quote_user = quote_message.from_user
    is_save_data = True
    forward_from_user = quote_message.forward_from
    if forward_from_user:
        quote_user = forward_from_user
    if (
        not (forward_from_user and quote_message.forward_sender_name)
        and update.effective_chat.type != "private"
    ):
        if not context.chat_data["members_data"].get(quote_user.id, None):
            member_data_obj = MemberData(
                id=quote_user.id,
                name=quote_user.full_name,
                msg_num=0,
                quote_num=0,
            )
            context.chat_data["members_data"][quote_user.id] = member_data_obj
        context.chat_data["members_data"][quote_user.id].quote_num += 1
    if quote_message.forward_sender_name and forward_from_user is None:
        is_save_data = False
    await context.bot.pin_chat_message(
        chat_id=update.effective_chat.id, message_id=quote_message.id
    )
    logger.debug(f"Bot将 {quote_message.text} 置顶")
    if not context.chat_data.get("quote_messages", None):
        context.chat_data["quote_messages"] = []
    if quote_message.id not in context.chat_data["quote_messages"]:
        context.chat_data["quote_messages"].append(quote_message.id)
        logger.debug(
            f"将{quote_message.id}([{update.effective_chat.title}]({quote_user.name}))"
            + "加入chat quote"
        )
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="已入典",
            reply_to_message_id=quote_message.id,
        )
    if not quote_message.text:
        # 如果不是文字消息, 在此处return
        return
    # 是文字消息
    if not is_save_data:
        return
    if not context.bot_data["quotes"].get(quote_user.id, None):
        context.bot_data["quotes"][quote_user.id] = {}
        context.bot_data["quotes"][quote_user.id]["img"] = []
        context.bot_data["quotes"][quote_user.id]["text"] = []
    for saved_quote_text_obj in context.bot_data["quotes"][quote_user.id]["text"]:
        saved_quote_text_obj: TextQuote
        if saved_quote_text_obj.content == quote_message.text:
            # 如果已经存在相同的文字, 直接
            return
    quote_text_obj = TextQuote(
        id=uuid1(), content=quote_message.text, created_at=datetime.now()
    )
    context.bot_data["quotes"][quote_user.id]["text"].append(quote_text_obj)
    logger.debug(f"[{quote_text_obj.content}]({quote_text_obj.id})" + "已保存")
    if len(quote_message.text) > 70:
        # 如果文字长度超过70, 则不生成图片, 直接
        return
    avatar_photo = (await context.bot.get_chat(chat_id=quote_user.id)).photo
    if not avatar_photo:
        # 如果没有头像, 或因为权限设置无法获取到头像, 直接
        return
    # 尝试生成图片
    try:
        avatar = await (await avatar_photo.get_big_file()).download_as_bytearray()
        quote_img = await generate_quote_img(
            avatar=avatar, text=quote_message.text, name=quote_user.name
        )
        sent_photo = await context.bot.send_photo(
            chat_id=update.effective_chat.id, photo=quote_img
        )
        photo_id = sent_photo.photo[0].file_id
        # 保存图像数据
        quote_img_obj = ImgQuote(
            id=uuid1(),
            content=photo_id,
            created_at=datetime.now(),
            text=quote_message.text,
        )
        context.bot_data["quotes"][quote_user.id]["img"].append(quote_img_obj)
    except Exception as e:
        await context.bot.send_message(
            chat_id=update.effective_chat.id, text=f"{e.__class__.__name__}: {e}"
        )
        logger.error(f"{e.__class__.__name__}: {e}")


async def set_quote_probability(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(
        f"[{update.effective_chat.title}]({update.effective_user.name})"
        + f" {update.effective_message.text}"
    )
    await message_recorder(update, context)
    if update.effective_chat.type != "private":
        admins = await context.bot.get_chat_administrators(
            chat_id=update.effective_chat.id
        )
        if (
            update.effective_user.id not in [admin.user.id for admin in admins]
            and update.effective_user.id not in settings["owners"]
        ):
            sent_message = await context.bot.send_message(
                chat_id=update.effective_chat.id, text="你没有权限哦"
            )
            logger.info(f"Bot: {sent_message.text}")
            return
    try:
        probability = float(update.effective_message.text.split(" ")[1])
    except ValueError:
        sent_message = await context.bot.send_message(
            chat_id=update.effective_chat.id, text="概率是在[0,1]之间的浮点数,请检查输入"
        )
        logger.info(f"Bot: {sent_message.text}")
        return
    except IndexError:
        sent_message = await context.bot.send_message(
            chat_id=update.effective_chat.id, text="请指定概率"
        )
        logger.info(f"Bot: {sent_message.text}")
        return
    if probability < 0 or probability > 1:
        sent_message = await context.bot.send_message(
            chat_id=update.effective_chat.id, text="概率是在[0,1]之间的浮点数,请检查输入"
        )
        logger.info(f"Bot: {sent_message.text}")
        return
    context.chat_data["quote_probability"] = probability
    sent_message = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"将本聊天的发典设置概率为{probability}啦",
    )
    logger.info(f"Bot: {sent_message.text}")


async def random_quote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    this_chat = update.effective_chat
    this_user = update.effective_user
    this_message = update.effective_message
    logger.info(
        f"[{this_chat.title}]({this_user.name})"
        + (f" {this_message.text}" if this_message.text else "<非文本消息>")
    )
    await message_recorder(update, context)
    if not random_unit(context.chat_data.get("quote_probability", 0.1)):
        return
    if not context.chat_data.get("quote_messages", None):
        return
    try:
        to_forward_message_id: int = random.choice(context.chat_data["quote_messages"])
        sent_message = await context.bot.forward_message(
            chat_id=update.effective_chat.id,
            from_chat_id=update.effective_chat.id,
            message_id=to_forward_message_id,
        )
        logger.info(
            "Bot: " + (f"{sent_message.text}" if sent_message.text else "<非文本消息>")
        )
    except BadRequest:
        logger.error(f"{to_forward_message_id} 未找到,从chat quote中移除")
        context.chat_data["quote_messages"].remove(to_forward_message_id)
        sent_message = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"有一条典突然消失了!\nid: _{to_forward_message_id}_\n已从chat quote中移除",
            parse_mode="MarkdownV2",
        )
        logger.info(f"Bot: {sent_message.text}")
    except Exception as e:
        logger.error(f"{e.__class__.__name__}: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id, text=f"{e.__class__.__name__}: {e}"
        )


async def del_quote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(
        f"[{update.effective_chat.title}]({update.effective_user.name})"
        + f" {update.effective_message.text}"
    )
    await message_recorder(update, context)
    if not context.chat_data.get("quote_messages", None):
        sent_message = await context.bot.send_message(
            chat_id=update.effective_chat.id, text="该聊天没有典呢"
        )
        logger.info(f"Bot: {sent_message.text}")
        return
    if not update.effective_message.reply_to_message:
        sent_message = await context.bot.send_message(
            chat_id=update.effective_chat.id, text="请回复要移出典的消息"
        )
        logger.info(f"Bot: {sent_message.text}")
        return
    quote_message = update.effective_message.reply_to_message
    if quote_message.id in context.chat_data["quote_messages"]:
        context.chat_data["quote_messages"].remove(quote_message.id)
        logger.debug(
            f"将{quote_message.id}([{update.effective_chat.title}]({update.effective_user.name}))"
            + "移出chat quote"
        )
        await context.bot.unpin_chat_message(
            chat_id=update.effective_chat.id, message_id=quote_message.id
        )
        logger.debug(
            "Bot将"
            + (f"{quote_message.text}" if quote_message.text else "<一条非文本消息>")
            + "取消置顶"
        )
        sent_message = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="已移出典",
            reply_to_message_id=quote_message.id,
        )
        logger.info(f"Bot: {sent_message.text}")
    else:
        sent_message = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="该消息不在典中;请对原始的典消息使用",
            reply_to_message_id=quote_message.id,
        )
        logger.info(f"Bot: {sent_message.text}")


async def clear_chat_quote_ask(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(
        f"[{update.effective_chat.title}]({update.effective_user.name})"
        + f" {update.effective_message.text}"
    )
    await message_recorder(update, context)
    if not context.chat_data.get("quote_messages", None):
        sent_message = await context.bot.send_message(
            chat_id=update.effective_chat.id, text="该聊天没有典呢"
        )
        logger.info(f"Bot: {sent_message.text}")
        return
    clear_chat_quote_markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("算了", callback_data="cancel_clear_chat_quote"),
                InlineKeyboardButton("确认清空", callback_data="clear_chat_quote"),
            ]
        ]
    )
    sent_message = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="真的要清空该聊天的典吗?\n\n用户个人数据不会被此操作清除",
        reply_markup=clear_chat_quote_markup,
    )
    logger.info(f"Bot: {sent_message.text}")


async def clear_chat_quote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.chat_data.get("quote_messages", None):
        return
    for message_id in context.chat_data["quote_messages"]:
        try:
            unpin_ok = await context.bot.unpin_chat_message(
                chat_id=update.effective_chat.id, message_id=message_id
            )
            if unpin_ok:
                logger.debug(f"Bot将{message_id}取消置顶")
        except BadRequest:
            continue
        except Exception as e:
            logger.error(e)
            await context.bot.send_message(
                chat_id=update.effective_chat.id, text=f"{e.__class__.__name__}: {e}"
            )
            time.sleep(0.5)
            continue
    context.chat_data["quote_messages"] = []
    sent_message = await context.bot.send_message(
        chat_id=update.effective_chat.id, text="已清空该聊天的典"
    )
    logger.info(f"Bot: {sent_message.text}")


async def clear_chat_quote_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.delete_message(
        chat_id=update.effective_chat.id, message_id=update.callback_query.message.id
    )


async def interact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(
        f"[{update.effective_chat.title}]({update.effective_user.name})"
        + f" {update.effective_message.text}"
    )
    await message_recorder(update, context)
    text = ""
    cmd = ""
    message_text = update.effective_message.text
    if reply_to_message := update.effective_message.reply_to_message:
        # 如果是对其他人使用
        this_user = update.effective_user
        replied_user = reply_to_message.from_user
        this_name = this_user.full_name
        replied_name = replied_user.full_name
        this_id = this_user.id
        replied_id = replied_user.id
        if len(message_text.split(" ")) == 1:
            if message_text.startswith("/"):
                cmd = message_text[1:].replace("/", "")
                text = f"[{this_name}](tg://user?id={this_id}){cmd}了[{replied_name}](tg://user?id={replied_id})!"  # noqa: E501

            elif message_text.startswith("\\"):
                cmd = message_text[1:]
                text = f"[{this_name}](tg://user?id={this_id})被[{replied_name}](tg://user?id={replied_id}){cmd}了!"  # noqa: E501
        else:
            if message_text.startswith("/"):
                cmd_front = message_text.split(" ")[0].replace("/", "")
                cmd_back = message_text.split(" ")[1:]
                cmd_back = " ".join(cmd_back).replace("/", "")
                text = f"[{this_name}](tg://user?id={this_id}){cmd_front}[{replied_name}](tg://user?id={replied_id}){cmd_back}!"  # noqa: E501
            elif message_text.startswith("\\"):
                cmd_front = message_text.split(" ")[0].replace("\\", "")
                cmd_back = message_text.split(" ")[1:]
                cmd_back = " ".join(cmd_back)
                text = f"[{replied_name}](tg://user?id={replied_id}){cmd_front}[{this_name}](tg://user?id={this_id}){cmd_back}!"  # noqa: E501
    else:
        # 如果是对自己使用
        if message_text.startswith("/"):
            cmd = message_text[1:].replace("/", "")
            text = f"[{update.effective_user.full_name}](tg://user?id={update.effective_user.id}){cmd}了自己!"  # noqa: E501
        elif message_text.startswith("\\"):
            cmd = message_text[1:]
            text = f"[{update.effective_user.full_name}](tg://user?id={update.effective_user.id})被自己{cmd}了!"  # noqa: E501
    sent_message = await context.bot.send_message(
        chat_id=update.effective_chat.id, text=text, parse_mode="Markdown"
    )
    logger.info(f"Bot: {sent_message.text}")


async def inline_query_quote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.inline_query.query
    user_id = update.inline_query.from_user.id
    user_name = update.inline_query.from_user.full_name
    quotes_data = context.bot_data["quotes"].get(user_id, {})
    text_quotes: list[TextQuote] = quotes_data.get("text", [])
    img_quotes: list[ImgQuote] = quotes_data.get("img", [])
    switch_pm_text = "名言管理"
    switch_pm_parameter = "start"
    is_personal = True
    cache_time = 10
    results = []
    no_quote_inline_markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "看看我的", url=f"https://t.me/{context.bot.username}?start=start"
                )
            ]
        ]
    )
    if not text_quotes and not img_quotes:
        results.append(
            InlineQueryResultArticle(
                id=uuid4(),
                title="你还没有保存任何名言",
                input_message_content=InputTextMessageContent("我还没有任何名言,史官快来为我记录吧!"),
                reply_markup=no_quote_inline_markup,
            )
        )
    else:
        if query:
            for text_quote in text_quotes:
                if query in text_quote.content:
                    create_at_str = text_quote.created_at.strftime("%Y年%m月%d日%H时%M分%S秒")
                    message_texts = [
                        f"[{user_name}](tg://user?id={user_id})在{create_at_str}曾言道:\n\n{text_quote.content}",
                        f"{text_quote.content}\n\n——[{user_name}](tg://user?id={user_id})在{create_at_str}说",
                        f"{text_quote.content}\n\n[{user_name}](tg://user?id={user_id})\n{create_at_str}",
                    ]
                    results.append(
                        InlineQueryResultArticle(
                            id=str(uuid4()),
                            title=text_quote.content,
                            input_message_content=InputTextMessageContent(
                                random.choice(message_texts), parse_mode="Markdown"
                            ),
                        )
                    )
            for img_quote in img_quotes:
                if query in img_quote.text:
                    create_at_str = img_quote.created_at.strftime("%Y年%m月%d日%H时%M分%S秒")
                    results.append(
                        InlineQueryResultCachedPhoto(
                            id=str(uuid4()),
                            photo_file_id=img_quote.content,
                            caption=f"[{user_name}](tg://user?id={user_id}), {create_at_str}",  # noqa: E501
                        )
                    )
            if len(results) == 0:
                results.append(
                    InlineQueryResultArticle(
                        id=str(uuid4()),
                        title="没有找到相关名言",
                        input_message_content=InputTextMessageContent(
                            message_text=f"我没有说过含有 _{query}_ 的名言!",
                            parse_mode="Markdown",
                        ),
                        reply_markup=no_quote_inline_markup,
                    )
                )
        else:
            results = []
            for text_quote in random.sample(text_quotes, min(len(text_quotes), 10)):
                create_at_str = text_quote.created_at.strftime("%Y年%m月%d日%H时%M分%S秒")
                message_texts = [
                    f"[{user_name}](tg://user?id={user_id})在{create_at_str}曾言道:\n\n{text_quote.content}",
                    f"{text_quote.content}\n\n——[{user_name}](tg://user?id={user_id})在{create_at_str}说",
                    f"{text_quote.content}\n\n[{user_name}](tg://user?id={user_id})\n{create_at_str}",
                ]
                results.append(
                    InlineQueryResultArticle(
                        id=str(uuid4()),
                        title=text_quote.content,
                        input_message_content=InputTextMessageContent(
                            message_text=random.choice(message_texts),
                            parse_mode="Markdown",
                        ),
                        description=f"于{text_quote.created_at}记",
                    )
                )

            for img_quote in random.sample(img_quotes, min(len(img_quotes), 10)):
                create_at_str = img_quote.created_at.strftime("%Y年%m月%d日%H时%M分%S秒")
                results.append(
                    InlineQueryResultCachedPhoto(
                        id=str(uuid4()),
                        photo_file_id=img_quote.content,
                        title=img_quote.text,
                        caption=f"[{user_name}](tg://user?id={user_id}), {create_at_str}",  # noqa: E501
                        parse_mode="Markdown",
                        description=f"图片, 记于{create_at_str}",
                    )
                )
    await context.bot.answer_inline_query(
        update.inline_query.id,
        results=results,
        cache_time=cache_time,
        is_personal=is_personal,
        switch_pm_text=switch_pm_text,
        switch_pm_parameter=switch_pm_parameter,
    )


async def user_data_manage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    img_quote_len = len(context.bot_data["quotes"].get(user_id, {}).get("img", []))
    text_quote_len = len(context.bot_data["quotes"].get(user_id, {}).get("text", []))
    quote_len = img_quote_len + text_quote_len
    pm_kmua_num = context.user_data.get("pm_kmua_num", 0) + 1
    context.user_data["pm_kmua_num"] = pm_kmua_num
    group_msg_num = context.user_data.get("group_msg_num", 0)
    text_num = context.user_data.get("text_num", 0)
    photo_num = context.user_data.get("photo_num", 0)
    sticker_num = context.user_data.get("sticker_num", 0)
    voice_num = context.user_data.get("voice_num", 0)
    video_num = context.user_data.get("video_num", 0)
    document_num = context.user_data.get("document_num", 0)
    user_data_manage_markup = InlineKeyboardMarkup(
        [[InlineKeyboardButton("❗清空", callback_data="clear_user_data")]]
    )
    statistics_data = f"""
你的统计信息:

你的ID: `{update.effective_user.id}`
已保存的名言总数: *{quote_len}*
图片名言数量: *{img_quote_len}*
文字名言数量: *{text_quote_len}*
私聊Kmua次数: *{pm_kmua_num}*
水群消息数: *{group_msg_num}*
总文字消息数: *{text_num}*
总图片消息数: *{photo_num}*
总贴纸消息数: *{sticker_num}*
总语音消息数: *{voice_num}*
总视频消息数: *{video_num}*
总文件消息数: *{document_num}*

点击下方清空按钮将立即删除以下数据:
1 已保存的名言总数
2 图片名言数量
3 文字名言数量
"""
    sent_message = await context.bot.edit_message_text(
        chat_id=update.effective_chat.id,
        text=statistics_data,
        reply_markup=user_data_manage_markup,
        parse_mode="MarkdownV2",
        message_id=update.callback_query.message.id,
    )
    logger.info(f"Bot: {sent_message.text}")


async def clear_user_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not context.bot_data["quotes"].get(user_id, {}):
        sent_message = await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            text="你还没有名言",
            message_id=update.callback_query.message.id,
        )
        logger.info(f"Bot: {sent_message.text}")
        return
    context.bot_data["quotes"][user_id] = {}
    await context.bot.edit_message_text(
        chat_id=update.effective_chat.id,
        message_id=update.callback_query.message.message_id,
        text="已清空你的名言录",
    )


async def help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(
        f"[{update.effective_chat.title}]({update.effective_user.name})"
        + f" {update.effective_message.text}"
    )
    await message_recorder(update, context)
    help_text = """
命令:
/help - 显示此帮助信息
/start - 开始使用
/q - 载入史册
/d - 移出史册
/c - 清空史册
/t - 获取头衔|互赠头衔
/setqp - 设置发典概率
/rank - 群统计信息

私聊:
可查询自己的统计信息
可删除自己的名言

互动:
对其他人使用 "/"命令 即可对其施法
例子:
A使用"/透"回复B的消息
Bot: "A透了B!"
使用反斜杠可主客互换

Inline 模式:
在任意聊天框艾特我即可使用,
支持搜索名言, 例如: @kmuav2bot 原神
"""
    help_markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("详细帮助", url="https://krau.github.io/kmua-bot/"),
                InlineKeyboardButton("源码", url="https://github.com/krau/kmua-bot"),
            ]
        ]
    )
    sent_message = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=help_text,
        reply_markup=help_markup,
    )
    logger.info(f"Bot: {sent_message.text}")


async def group_rank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(
        f"[{update.effective_chat.title}]({update.effective_user.name})"
        + f" {update.effective_message.text}"
    )
    await message_recorder(update, context)
    msg_num = context.chat_data["msg_num"]
    members_data = context.chat_data.get("members_data", {})
    if len(members_data) < 3:
        sent_message = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="数据不足,请多水水群吧~",
            reply_to_message_id=update.effective_message.message_id,
        )
        logger.info(f"Bot: {sent_message.text}")
        return
    msg_num_top: list[MemberData] = sort_topn_bykey(
        members_data, min(3, len(members_data)), "msg_num"
    )
    quote_num_top: list[MemberData] = sort_topn_bykey(
        members_data, min(3, len(members_data)), "quote_num"
    )
    quote_num = len(context.chat_data.get("quote_messages", {}))

    msg_top1 = msg_num_top[0]
    msg_top2 = msg_num_top[1]
    msg_top3 = msg_num_top[2]
    quote_top1 = quote_num_top[0]
    quote_top2 = quote_num_top[1]
    quote_top3 = quote_num_top[2]
    text = f"""
截止到 {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}:

本群共水了 *{msg_num}* 条消息,

共有 *{quote_num}* 条名言,

B话王排行榜:
1 [{msg_top1.name}](tg://user?id={msg_top1.id}) : *{msg_top1.msg_num}* 条
2 [{msg_top2.name}](tg://user?id={msg_top2.id}) : *{msg_top2.msg_num}* 条
3 [{msg_top3.name}](tg://user?id={msg_top3.id}) : *{msg_top3.msg_num}* 条

名言排行榜:
1 [{quote_top1.name}](tg://user?id={quote_top1.id}) : *{quote_top1.quote_num}* 条
2 [{quote_top2.name}](tg://user?id={quote_top2.id}) : *{quote_top2.quote_num}* 条
3 [{quote_top3.name}](tg://user?id={quote_top3.id}) : *{quote_top3.quote_num}* 条
"""

    sent_message = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=text,
        parse_mode="Markdown",
    )
    logger.info(f"Bot: {sent_message.text}")
