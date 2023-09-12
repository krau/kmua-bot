import asyncio
import random
from itertools import chain
from math import ceil, sqrt
import typing

import graphviz
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, User, Chat
from telegram.constants import ChatAction, ChatID
from telegram.error import BadRequest
from telegram.ext import ContextTypes
from telegram.helpers import escape_markdown

from ..config.config import settings
from ..logger import logger
from ..utils import message_recorder
from ..database import dao
from ..database.model import UserData


# def render_waifu_graph(relationships, user_info) -> bytes:
#     """
#     Render waifu graph and return the image bytes
#     :param relationships: a generator that yields (int, int) for (user_id, waifu_id)
#     :param user_info: a dict, user_id -> {"avatar": Optional[bytes], "username": str}
#     :return: bytes
#     """
#     dpi = max(150, ceil(5 * sqrt(len(user_info) / 3)) * 20)
#     graph = graphviz.Digraph(graph_attr={"dpi": str(dpi)})

#     try:
#         # Create nodes
#         for user_id, info in user_info.items():
#             username = info.get("username")
#             avatar = info.get("avatar")

#             if avatar is not None:
#                 avatar_path = avatar

#                 # Create a subgraph for each node
#                 with graph.subgraph(name=f"cluster_{user_id}") as subgraph:
#                     # Set the attributes for the subgraph
#                     subgraph.attr(label=username)
#                     subgraph.attr(shape="none")
#                     subgraph.attr(image=str(avatar_path))
#                     subgraph.attr(imagescale="true")
#                     subgraph.attr(fixedsize="true")
#                     subgraph.attr(width="1")
#                     subgraph.attr(height="1")
#                     subgraph.attr(labelloc="b")  # Label position at the bottom

#                     # Create a node within the subgraph
#                     subgraph.node(
#                         str(user_id),
#                         label="",
#                         shape="none",
#                         image=str(avatar_path),
#                         imagescale="true",
#                         fixedsize="true",
#                         width="1",
#                         height="1",
#                     )
#             else:
#                 # Create regular node without avatar image
#                 graph.node(str(user_id), label=username)

#         # Create edges
#         for user_id, waifu_id in relationships:
#             graph.edge(str(user_id), str(waifu_id))

#         return graph.pipe(format="webp")

#     except Exception:
#         raise


# async def waifu_graph(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     logger.info(
#         f"[{update.effective_chat.title}]({update.effective_user.name})"
#         + f" {update.effective_message.text}"
#     )

#     msg_id = update.effective_message.id
#     chat_id = update.effective_chat.id

#     await _waifu_graph(chat_id, context, msg_id)


# async def _waifu_graph(
#     chat_id: int,
#     context: ContextTypes.DEFAULT_TYPE,
#     msg_id: int | None = None,
# ):
#     today_waifu = context.bot_data["today_waifu"]
#     if not today_waifu.get(chat_id, None):
#         await context.bot.send_message(
#             chat_id, "群里还没有老婆！", reply_to_message_id=msg_id
#         )  # noqa: E501
#         return

#     waifu_mutex = context.bot_data["waifu_mutex"]
#     if waifu_mutex.get(chat_id, False):
#         return

#     today_waifu = today_waifu[chat_id].copy()

#     waifu_mutex[chat_id] = True

#     try:
#         relationships = (
#             (user_id, waifu_info["waifu"])
#             for user_id, waifu_info in today_waifu.items()
#             if waifu_info.get("waifu", None)
#         )
#         users = set(
#             chain(
#                 (
#                     waifu_info["waifu"]
#                     for waifu_info in today_waifu.values()
#                     if waifu_info.get("waifu", None)
#                 ),
#                 today_waifu.keys(),
#             )
#         )

#         status_msg = await context.bot.send_message(
#             chat_id, "少女祈祷中...", reply_to_message_id=msg_id
#         )

#         all_user_info = context.bot_data["user_info"]
#         user_info = {
#             user_id: {
#                 "username": all_user_info[user_id]["username"],
#                 "avatar": all_user_info[user_id]["avatar"],
#             }
#             for user_id in users
#             if user_id in all_user_info
#         }
#         missing_users = users - set(user_info.keys())
#         if missing_users:
#             logger.debug(f"getting missing users: {missing_users}")
#             for user_id in missing_users:
#                 retry = 0
#                 is_success = False
#                 user = None
#                 while retry < 3 and not is_success:
#                     try:
#                         user = await context.bot.get_chat(user_id)
#                         is_success = True
#                     except Exception as err:
#                         logger.error(f"获取waifu信息时出错: {err}")
#                         retry += 1
#                         await asyncio.sleep(1)
#                 if not is_success:
#                     logger.debug(f"cannot get chat for {user_id}")
#                     user_info[user_id] = {
#                         "username": f"id: {user_id}",
#                         "avatar": None,
#                     }
#                     continue
#                 username = user.username or f"id: {user_id}"
#                 avatar = user.photo
#                 if avatar:
#                     avatar = await (
#                         await user.photo.get_small_file()
#                     ).download_to_drive(f"{avatars_dir}/{user_id}.png")

#                 user_info[user_id] = {
#                     "username": username,
#                     "avatar": avatar,
#                 }

#                 context.bot_data["user_info"][user_id] = {
#                     "username": username,
#                     "avatar": avatar,
#                     "avatar_big_id": None,
#                     "full_name": user.full_name,
#                 }
#         try:
#             await context.bot.send_chat_action(chat_id, ChatAction.TYPING)
#             image_bytes = render_waifu_graph(relationships, user_info)
#             logger.debug(f"image_size: {len(image_bytes)}")
#             await context.bot.send_document(
#                 chat_id,
#                 document=image_bytes,
#                 caption=f"老婆关系图\n {len(users)} users",
#                 filename="waifu_graph.webp",
#                 disable_content_type_detection=True,
#                 reply_to_message_id=msg_id,
#                 allow_sending_without_reply=True,
#             )
#         except Exception as e:
#             await context.bot.send_message(
#                 chat_id,
#                 f"呜呜呜... kmua 被玩坏惹\n{e.__class__.__name__}: {e}",
#                 reply_to_message_id=msg_id,
#             )
#             logger.error(f"生成waifu图时出错: {e}")
#         finally:
#             await status_msg.delete()
#     except Exception:
#         raise
#     finally:
#         waifu_mutex[chat_id] = False
#         await context.application.persistence.flush()


async def today_waifu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    logger.info(f"[{chat.title}]({user.name})" + f" {update.effective_message.text}")

    if context.user_data.get("waifu_waiting", False):
        return

    context.user_data["waifu_waiting"] = True

    waifu: UserData = None
    await message_recorder(update, context)
    try:
        await context.bot.send_chat_action(chat.id, ChatAction.TYPING)
        waifu, is_got_waifu = await _get_waifu_for_user(update, context, user, chat)
        if not waifu:
            return
        dao.put_user_waifu_in_chat(user, chat, waifu)
        text = _get_waifu_text(waifu, is_got_waifu)
        waifu_markup = _get_waifu_markup(waifu, user)

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
    except Exception:
        raise
    finally:
        context.user_data["waifu_waiting"] = False
        dao.commit()


async def _get_waifu_for_user(
    update: Update, context: ContextTypes.DEFAULT_TYPE, user: User, chat: Chat
) -> (UserData | None, bool):
    """
    Get a waifu for user

    :return: (waifu, is_got_waifu)
    """
    if waifu := dao.get_user_waifu_in_chat(user, chat):
        return waifu, True
    group_member = await _get_chat_members_id_to_get_waifu(update, context, user, chat)
    if not group_member:
        return None, False
    waifu_id = random.choice(group_member)
    while retry := 0 < 3:
        try:
            if waifu := dao.get_user_by_id(waifu_id):
                return waifu, False
            else:
                waifu_chat = await context.bot.get_chat(waifu_id)
                waifu = dao.add_user(waifu_chat)
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
    group_member: list[int] = dao.get_chat_members_id(chat)
    married = dao.get_married_users_id_in_chat(chat)
    must_remove = [
        user.id,
        context.bot.id,
        ChatID.FAKE_CHANNEL,
        ChatID.ANONYMOUS_ADMIN,
        ChatID.SERVICE_CHAT,
    ]
    to_remove = set(married + must_remove)
    group_member = [i for i in group_member if i not in to_remove]
    if not group_member:
        await update.message.reply_text(text="你现在没有老婆, 因为咱的记录中找不到其他群友")
        return None
    return group_member


def _get_waifu_text(waifu: User | UserData, is_got_waifu: bool) -> str:
    return (
        (
            f"你今天已经抽过老婆了\! [{escape_markdown(waifu.full_name,2)}](tg://user?id={waifu.id}) 是你今天的老婆\!"  # noqa: E501
            if is_got_waifu
            else f"你今天的群幼老婆是 [{escape_markdown(waifu.full_name,2)}](tg://user?id={waifu.id}) \!"  # noqa: E501
        )
        if waifu.waifu_mention
        else (
            f"你今天已经抽过老婆了\! {escape_markdown(waifu.full_name,2)} 是你今天的老婆\!"  # noqa: E501
            if is_got_waifu
            else f"你今天的群幼老婆是 {escape_markdown(waifu.full_name,2)} \!"
        )
    )


def _get_waifu_markup(
    waifu: User | UserData, user: User | UserData
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    text="从卡池中移除",
                    callback_data=f"remove_waifu {waifu.id} {user.id}",
                )
            ]
        ]
    )


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


async def clear_chat_waifu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(
        f"[{update.effective_chat.title}]({update.effective_user.name})"
        + f" {update.effective_message.text}"
    )
    if len(context.args) == 0:
        if update.effective_chat.type == "private":
            await update.message.reply_text(text="请在群组中使用此命令")
            return
        try:
            this_chat_member = await update.effective_chat.get_member(
                update.effective_user.id
            )
        except BadRequest as e:
            if e.message == "User not found":
                await update.message.reply_text(
                    text="无法获取信息, 如果群组开启了隐藏成员, 请赋予 bot 管理员权限",
                )
                return
            else:
                raise e
        if this_chat_member.status != "creator":
            await update.message.reply_text(text="你没有权限哦, 只有群主可以清空老婆数据")  # noqa: E501
            return
        context.bot_data["today_waifu"][update.effective_chat.id] = {}
        await context.application.persistence.flush()
        await update.message.reply_text(text="已清除本群今日老婆数据")
    else:
        if update.effective_user.id not in settings.owners:
            return
        chat_id = int(context.args[0])
        if not context.bot_data["today_waifu"].get(chat_id, None):
            await update.message.reply_text(text=f"群组 {chat_id} 还没有老婆数据")
            return
        context.bot_data["today_waifu"][chat_id] = {}
        await context.application.persistence.flush()
        await update.message.reply_text(text=f"已清除群组 {chat_id} 的今日老婆数据")
