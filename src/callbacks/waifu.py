import asyncio
import random
from itertools import chain

import shutil
import graphviz
import tempfile
import os

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from ..logger import logger
from ..utils import message_recorder
from ..config.config import settings


async def migrate_waifu_shutdown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in settings.owners:
        msg_id = update.effective_message.id
        msg = await context.bot.send_message(
            chat_id=msg_id, text="呜呜... 你不是咱的主人！", reply_to_message_id=msg_id
        )
        await asyncio.sleep(5)
        await msg.delete()
        return

    new_today_waifu = {}

    for user_id, user_data in context.bot_data["today_waifu"].items():
        logger.info(f"migrating for {user_id}...")
        for chat_id, waifu_id in user_data.items():
            if not new_today_waifu.get(chat_id, None):
                new_today_waifu[chat_id] = {}

            new_today_waifu[chat_id][user_id] = {"waifu": waifu_id, "waiting": False}

    logger.info("migration finished!")
    await context.bot.shutdown()


def render_waifu_graph(relationships, user_info) -> bytes:
    """
    Render waifu graph and gives png bytes
    :param relationships: a generator that yields (int, int) for (user_id, waifu_id)
    :param user_info: a dict, user_id -> {"avatar": Optional[bytes], "username": str}
    :return: str - path to the temporary image file
    """
    graph = graphviz.Digraph()

    temp_dir = (
        tempfile.mkdtemp()
    )  # Create a temporary directory to store the image file

    try:
        # Create nodes
        for user_id, info in user_info.items():
            username = info.get("username")
            avatar = info.get("avatar")

            if avatar is not None:
                # Save avatar to a temporary file
                avatar_path = os.path.join(temp_dir, f"{user_id}_avatar.png")
                with open(avatar_path, "wb") as avatar_file:
                    avatar_file.write(avatar)

                # Create a subgraph for each node
                with graph.subgraph(name=f"cluster_{user_id}") as subgraph:
                    # Set the attributes for the subgraph
                    subgraph.attr(label=username)
                    subgraph.attr(shape="none")
                    subgraph.attr(image=avatar_path)
                    subgraph.attr(imagescale="true")
                    subgraph.attr(fixedsize="true")
                    subgraph.attr(width="1")
                    subgraph.attr(height="1")

                    # Create a node within the subgraph
                    subgraph.node(
                        str(user_id),
                        label="",
                        shape="none",
                        image=avatar_path,
                        imagescale="true",
                        fixedsize="true",
                        width="1",
                        height="1",
                    )
            else:
                # Create regular node without avatar image
                graph.node(str(user_id), label=username)

        # Create edges
        for user_id, waifu_id in relationships:
            graph.edge(str(user_id), str(waifu_id))

        return graph.pipe(format="png")

    except Exception as e:
        raise e

    finally:
        # Clean up the temporary directory
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)


async def waifu_graph(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(
        f"[{update.effective_chat.title}]({update.effective_user.name})"
        + f" {update.effective_message.text}"
    )

    msg_id = update.effective_message.id
    chat_id = update.effective_chat.id

    await _waifu_graph(chat_id, context, msg_id)


async def _waifu_graph(
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
    msg_id: int | None = None,
):
    today_waifu = context.bot_data["today_waifu"]
    if not today_waifu.get(chat_id, None):
        await context.bot.send_message(chat_id, "群里还没有老婆！", reply_to_message_id=msg_id)
        return

    waifu_mutex = context.bot_data["waifu_mutex"]
    if waifu_mutex.get(chat_id, False):
        return

    waifu_mutex[chat_id] = True

    try:
        relationships = (
            (user_id, waifu_info["waifu"])
            for user_id, waifu_info in today_waifu[chat_id].items()
            if waifu_info.get("waifu", None)
        )
        users = set(
            chain(
                (
                    waifu_info["waifu"]
                    for waifu_info in today_waifu[chat_id].values()
                    if waifu_info.get("waifu", None)
                ),
                today_waifu[chat_id].keys(),
            )
        )

        loaded_user = 0
        status_msg = await context.bot.send_message(
            chat_id, "少女祈祷中...", reply_to_message_id=msg_id
        )

        user_info = {}
        for user_id in users:
            retry = 5
            successed = False
            for i in range(retry):
                try:
                    user = await context.bot.get_chat(user_id)
                    successed = True
                except Exception as err:
                    logger.error(f"获取waifu信息时出错: {err}")
                    await asyncio.sleep(1)

            if not successed:
                logger.debug(f"cannot get chat for {user_id}")

                user_info[user_id] = {
                    "username": f"id: {user_id}",
                    "avatar": None,
                }

                continue

            username = user.username or f"id: {user_id}"
            avatar = user.photo
            if avatar:
                avatar = await (
                    await user.photo.get_small_file()
                ).download_as_bytearray()
                avatar = bytes(avatar)

            user_info[user_id] = {
                "username": username,
                "avatar": avatar if successed else None,
            }
            loaded_user += 1

        try:
            await context.bot.send_chat_action(chat_id, ChatAction.TYPING)
            image_bytes = render_waifu_graph(relationships, user_info)
            logger.debug(f"image_size: {len(image_bytes)}")
            await context.bot.send_document(
                chat_id,
                document=image_bytes,
                caption=f"老婆关系图\nloaded {loaded_user} of {len(users)} users",
                filename="waifu_graph.png",
                reply_to_message_id=msg_id,
                allow_sending_without_reply=True,
            )
        except Exception as e:
            await context.bot.send_message(
                chat_id,
                f"呜呜呜... kmua被 玩坏惹\n{e.__class__.__name__}: {e}",
                reply_to_message_id=msg_id,
            )
            logger.error(f"生成waifu图时出错: {e}")
        finally:
            await status_msg.delete()
    except Exception as err:
        raise err
    finally:
        waifu_mutex[chat_id] = False
        await context.application.persistence.flush()


async def today_waifu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(
        f"[{update.effective_chat.title}]({update.effective_user.name})"
        + f" {update.effective_message.text}"
    )
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    if context.bot_data["waifu_mutex"].get(chat_id, False):
        return

    if not context.bot_data["today_waifu"].get(chat_id, None):
        context.bot_data["today_waifu"][chat_id] = {}
    if not context.bot_data["today_waifu"][chat_id].get(user_id, None):
        context.bot_data["today_waifu"][chat_id][user_id] = {}
    if context.bot_data["today_waifu"][chat_id][user_id].get("waiting", False):
        return
    context.bot_data["today_waifu"][chat_id][user_id]["waiting"] = True

    await message_recorder(update, context)
    try:
        await context.bot.send_chat_action(chat_id, ChatAction.TYPING)
        is_got_waifu = True
        is_success = False
        waifu_id = context.bot_data["today_waifu"][chat_id][user_id].get("waifu", None)
        if not waifu_id:
            is_got_waifu = False
            group_member: list[int] = list(context.chat_data["members_data"].keys())
            to_remove = [
                user_id,
                5304501737,
                1031952739,
                609517172,
                777000,
                136817688,
                1087968824,
                context.bot.id,
            ]
            group_member = [
                member for member in group_member if member not in to_remove
            ]
            if not group_member:
                await update.message.reply_text(text="你现在没有老婆, 因为咱的记录中找不到其他群友")
                return
            waifu_id = random.choice(group_member)

        retry = 0
        err = None
        while not is_success and retry < 3:
            try:
                waifu = await context.bot.get_chat(waifu_id)
                is_success = True
            except Exception as e:
                logger.error(
                    f"无法为 {update.effective_user.name} 获取id为 {waifu_id} 的waifu:\n{e.__class__.__name__}: {e}"
                )
                retry += 1
                err = e
                waifu_id = random.choice(group_member)
                await asyncio.sleep(1)

        if not is_success:
            await update.message.reply_text(text="你没能抽到老婆, 再试一次吧~")
            poped_value = context.chat_data["members_data"].pop(waifu_id, "群组数据中无该成员")
            logger.debug(f"移除: {poped_value}")
            raise err
        else:
            context.bot_data["today_waifu"][chat_id][user_id]["waifu"] = waifu.id

        avatar = waifu.photo
        if avatar:
            avatar = await (await waifu.photo.get_big_file()).download_as_bytearray()
            avatar = bytes(avatar)
        is_mention_waifu = (
            (await context.application.persistence.get_user_data())
            .get(waifu_id, {})
            .get("waifu_is_mention", True)
        )
        try:
            if is_mention_waifu:
                if is_got_waifu:
                    text = f"你今天已经抽过老婆了! {waifu.mention_html()} 是你今天的老婆!"
                else:
                    text = f"你今天的群幼老婆是 {waifu.mention_html()} !"
            else:
                if is_got_waifu:
                    text = f"你今天已经抽过老婆了! {waifu.full_name} 是你今天的老婆!"
                else:
                    text = f"你今天的群幼老婆是 {waifu.full_name} !"
        except TypeError as e:
            logger.error(
                f"无法为 {update.effective_user.name} 获取id为 {waifu_id} 的waifu:\n{e.__class__.__name__}: {e}"
            )
            if is_got_waifu:
                text = f"你的老婆消失了...TA的id曾是: {waifu_id}"
            else:
                text = "你没能抽到老婆, 再试一次吧~"
            await update.message.reply_text(text=text)
            poped_value = context.chat_data["members_data"].pop(waifu_id, "群组数据中无该成员")
            context.bot_data["today_waifu"][user_id][chat_id] = None
            logger.debug(f"移除: {poped_value}")
            return
        if not update.message:
            return
        today_waifu_markup = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        text="从卡池中移除",
                        callback_data=f"remove_waifu {waifu_id} {user_id}",
                    )
                ]
            ]
        )
        if avatar:
            try:
                await update.message.reply_photo(
                    photo=avatar,
                    caption=text,
                    parse_mode="HTML",
                    reply_markup=today_waifu_markup,
                )
            except BadRequest as e:
                if e.message == "Not enough rights to send photos to the chat":
                    await update.message.reply_html(
                        text=text, reply_markup=today_waifu_markup
                    )
                else:
                    raise e
            except Exception as e:
                raise e
        else:
            await update.message.reply_html(text=text, reply_markup=today_waifu_markup)
        logger.info(f"Bot: {text}")
    except Exception as e:
        raise e
    finally:
        context.bot_data["today_waifu"][chat_id][user_id]["waiting"] = False
        await context.application.persistence.flush()


async def remove_waifu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        this_chat_member = await update.effective_chat.get_member(
            update.effective_user.id
        )
    except BadRequest as e:
        if e.message == "User not found":
            await update.callback_query.answer(
                text="无法获取信息, 如果群组开启了隐藏成员, 请赋予 bot 管理员权限",
                show_alert=True,
            )
            return
        else:
            raise e

    if this_chat_member.status != "creator":
        await context.bot.answer_callback_query(
            callback_query_id=update.callback_query.id,
            text="你没有权限哦, 只有群主可以移除卡池",
        )
        return
    data = update.callback_query.data.split(" ")
    waifu_id = int(data[1])
    user_id = int(data[2])
    message = update.callback_query.message
    waifuname = None
    for entity in message.caption_entities:
        if entity.type == "text_mention":
            waifuname = entity.user.name
            break
    if not waifuname:
        waifuname = waifu_id
    try:
        user = await context.bot.get_chat(user_id)
        username = user.username or user.full_name
    except Exception:
        username = user_id
    poped_value = context.chat_data["members_data"].pop(waifu_id, "群组数据中无该成员")
    logger.debug(f"移除: {poped_value}")

    chat_id = update.effective_chat.id
    if context.bot_data["today_waifu"][chat_id]:
        context.bot_data["today_waifu"][chat_id].pop(user_id, None)
    await update.callback_query.message.delete()
    await update.effective_chat.send_message(
        text=f"已从本群数据中移除 {waifuname}, {username} 可以重新抽取",
    )


async def user_waifu_manage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    is_mention = context.user_data.get("waifu_is_mention", True)
    set_mention_text = "别@你" if is_mention else "抽到你时@你"
    waifu_manage_markup = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(text=set_mention_text, callback_data="set_mention")],
            [InlineKeyboardButton(text="返回", callback_data="back_home")],
        ]
    )
    text = f"""
当前设置:
是否@你: {is_mention}"""
    await update.callback_query.message.edit_text(
        text=text, reply_markup=waifu_manage_markup
    )
    await context.application.persistence.flush()


async def set_mention(update: Update, context: ContextTypes.DEFAULT_TYPE):
    is_mention = context.user_data.get("waifu_is_mention", True)
    context.user_data["waifu_is_mention"] = not is_mention
    is_mention = context.user_data["waifu_is_mention"]
    set_mention_text = "别@你" if is_mention else "抽到你时@你"
    waifu_manage_markup = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(text=set_mention_text, callback_data="set_mention")],
            [InlineKeyboardButton(text="返回", callback_data="back_home")],
        ]
    )
    text = f"""
当前设置:
是否@你: {is_mention}"""
    await update.callback_query.message.edit_text(
        text=text, reply_markup=waifu_manage_markup
    )
    await context.application.persistence.flush()


async def clear_waifu_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in settings.owners:
        return
    context.bot_data["today_waifu"] = {}
    context.bot_data["waifu_mutex"] = {}
    await context.application.persistence.flush()
    await update.message.reply_text(text="已清除今日老婆数据")
