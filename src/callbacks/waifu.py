import asyncio
import io
import random
from itertools import chain
from typing import Optional

import networkx as nx
from matplotlib import offsetbox
from matplotlib import pyplot as plt
from PIL import Image
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from ..logger import logger
from ..utils import message_recorder
from ..config.config import settings


def render_waifu_graph(relationships, user_info) -> bytes:
    """
    render waifu graph
    :param relationships: a generator yields (int, int) for (user_id, waifu_id)
    :param user_info: a dict, user_id -> {"avatar": Optional[bytes], "username": str}
    :return: bytes
    """
    G = nx.DiGraph()

    G.add_edges_from(relationships)
    # 创建节点标签和图像字典
    labels = {}
    img_dict = {}
    for user_id, info in user_info.items():
        username = info.get("username")
        avatar = info.get("avatar")

        labels[user_id] = username

        if avatar is not None:
            img_dict[user_id] = avatar

    plt.figure(
        layout="constrained",
        figsize=(1.2 * 1.414 * len(user_info), 1.2 * 1.414 * len(user_info)),
    )

    # 绘制图形
    pos = nx.spring_layout(G, seed=random.randint(1, 10000), k=2.0)  # 设定节点位置

    nx.draw_networkx_edges(
        G,
        pos,
        arrows=True,
        arrowsize=18,
        arrowstyle="fancy",
        edge_color=(0.2, 0.5, 0.8, 0.5),
    )
    nx.draw_networkx_labels(
        G,
        pos,
        labels=(
            {user: waifu for user, waifu in labels.items() if user not in img_dict}
        ),
    )

    for node_id, pos in pos.items():
        if node_id not in img_dict:
            continue

        img_data = img_dict[node_id]
        img = Image.open(io.BytesIO(img_data))

        combined_box = offsetbox.VPacker(
            children=[
                offsetbox.OffsetImage(img, zoom=0.5),
                offsetbox.TextArea(labels[node_id], {}),
            ],
            align="center",
            pad=0,
            sep=5,
        )

        imagebox = offsetbox.AnnotationBbox(combined_box, pos, frameon=False)
        plt.gca().add_artist(imagebox)

    plt.axis("off")  # 关闭坐标轴

    # 将图形保存为字节数据
    buf = io.BytesIO()
    plt.savefig(buf, format="png")
    plt.close()
    # 获取字节数据并返回
    buf.seek(0)
    image_bytes = buf.read()
    buf.close()
    return image_bytes


async def waifu_graph(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(
        f"[{update.effective_chat.title}]({update.effective_user.name})"
        + f" {update.effective_message.text}"
    )

    msg_id = update.effective_message.id
    chat_id = update.effective_chat.id

    await _waifu_graph(msg_id, chat_id, context)


async def _waifu_graph(
    msg_id: Optional[int], chat_id: int, context: ContextTypes.DEFAULT_TYPE
):
    today_waifu = context.bot_data["today_waifu"]
    if not today_waifu.get(chat_id, None):
        await context.bot.send_message(chat_id, "群里还没有老婆！", reply_to_message_id=msg_id)
        return

    waifu_mutex = context.bot_data["waifu_mutex"]
    if waifu_mutex.get(chat_id, False):
        message = await context.bot.send_message(
            chat_id, "呜呜.. 不许看！等人家换好衣服啦", reply_to_message_id=msg_id
        )
        await asyncio.sleep(3)
        await message.delete()
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
            chat_id, f"少女祈祷中... {loaded_user}/{len(users)}", reply_to_message_id=msg_id
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
            await status_msg.edit_text(f"少女祈祷中... {loaded_user}/{len(users)}")

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
                chat_id, f"呜呜呜... kmua被 玩坏惹\n{e}", reply_to_message_id=msg_id
            )
            logger.error(f"生成waifu图时出错: {e}")

        await status_msg.delete()
    except Exception as err:
        raise err
    finally:
        waifu_mutex[chat_id] = False


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
                    text = f"你今天的群友老婆是 {waifu.mention_html()} !"
            else:
                if is_got_waifu:
                    text = f"你今天已经抽过老婆了! {waifu.full_name} 是你今天的老婆!"
                else:
                    text = f"你今天的群友老婆是 {waifu.full_name} !"
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
    await context.application.persistence.flush()
    await update.message.reply_text(text="已清除今日老婆数据")
