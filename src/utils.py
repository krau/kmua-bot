import io
import os
import random
import re
from operator import attrgetter
from pathlib import Path
from typing import Generator

from PIL import Image, ImageFont
from pilmoji import Pilmoji
from telegram import (
    Chat,
    Message,
    Update,
    User,
)
from telegram.constants import ChatID, ChatMemberStatus, ChatType
from telegram.ext import ContextTypes

from .config.config import settings
from .database import dao
from .database.model import ChatData
from .logger import logger

fake_users_id = [ChatID.FAKE_CHANNEL, ChatID.ANONYMOUS_ADMIN, ChatID.SERVICE_CHAT]


def random_unit(probability: float) -> bool:
    """
    以probability的概率返回True

    :param probability: 概率
    :return: bool
    """
    assert 0 <= probability <= 1, "参数probability应该在[0,1]之间"
    return random.uniform(0, 1) < probability


async def message_recorder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    message = update.effective_message
    if not user or not chat:
        return
    if message.reply_to_message or chat.type == ChatType.CHANNEL:
        return
    if message.sender_chat:
        user = message.sender_chat
    db_user = dao.add_user(user)
    if chat.type == ChatType.GROUP or chat.type == ChatType.SUPERGROUP:
        dao.add_user_to_chat(db_user, chat)


async def generate_quote_img(avatar: bytes, text: str, name: str) -> bytes:
    text = text.replace("\n", " ")
    font_path = str(Path(__file__).resolve().parent.parent / "resource" / "TsukuA.ttc")
    font_size = 42
    font = ImageFont.truetype(font_path, font_size)
    base_img = Image.open(
        os.path.join(Path(os.path.dirname(__file__)).parent, "resource", "base.png")
    )
    img = Image.new("RGBA", (1200, 630), (255, 255, 255, 0))
    avatar = Image.open(io.BytesIO(avatar))
    img.paste(avatar, (0, 0))
    img.paste(base_img, (0, 0), base_img)

    text_list = [text[i : i + 18] for i in range(0, len(text), 18)]
    new_text_height = font_size * len(text_list)
    new_text_width = max([font.getsize(x)[0] for x in text_list])
    text_x = 540 + int((560 - new_text_width) / 2)
    text_y = int((630 - new_text_height) / 2)
    with Pilmoji(img) as pilmoji:
        for i in range(len(text_list)):
            pilmoji.text(
                (text_x, text_y + i * font_size),
                text=text_list[i],
                fill=(255, 255, 252),
                font=font,
                align="center",
                emoji_position_offset=(0, 12),
            )

    name_font_size = 24
    name_font = ImageFont.truetype(font_path, name_font_size)
    name_width, name_height = name_font.getsize(name)
    name_x = 600 + int((560 - name_width) / 2)
    name_y = 630 - name_height - 20
    with Pilmoji(img) as pilmoji:
        pilmoji.text(
            (name_x, name_y),
            text=f"{name}",
            font=name_font,
            fill=(255, 255, 252),
            align="center",
        )
    img_byte_arr = io.BytesIO()
    img = img.convert("RGB")
    img.save(img_byte_arr, format="png")
    img_byte_arr = img_byte_arr.getvalue()
    return img_byte_arr


def sort_topn_bykey(data: dict, n: int, key: str) -> list:
    """
    将字典按照指定的key排序，取前n个

    :param data: 字典
    :param n: 取前n个
    :param key: 指定的key
    :return: 排序后的列表
    """
    return sorted(data.values(), key=attrgetter(key), reverse=True)[:n]


def parse_arguments(text: str) -> list[str]:
    pattern = r'"([^"]*)"|([^ ]+)'
    arguments = re.findall(pattern, text)
    parsed_arguments = [group[0] or group[1] for group in arguments]

    return parsed_arguments


async def get_big_avatar_bytes(
    chat_id: int, context: ContextTypes.DEFAULT_TYPE
) -> bytes | None:
    db_user = dao.get_user_by_id(chat_id)
    if db_user:
        if db_user.avatar_big_blob:
            return db_user.avatar_big_blob
        else:
            avatar = await download_big_avatar(chat_id, context)
            if avatar:
                db_user.avatar_big_blob = avatar
                dao.commit()
            return avatar
    else:
        return await download_big_avatar(chat_id, context)


async def download_big_avatar(
    chat_id: int, context: ContextTypes.DEFAULT_TYPE
) -> bytes | None:
    try:
        avatar_photo = (await context.bot.get_chat(chat_id=chat_id)).photo
        if not avatar_photo:
            return None
        avatar = await (await avatar_photo.get_big_file()).download_as_bytearray()
        avatar = bytes(avatar)
        return avatar
    except Exception as err:
        logger.error(f"{err.__class__.__name__}: {err} happend when getting big avatar")
        return None


async def get_small_avatar_bytes(
    chat_id: int, context: ContextTypes.DEFAULT_TYPE
) -> bytes | None:
    db_user = dao.get_user_by_id(chat_id)
    if db_user:
        if db_user.avatar_small_blob:
            return db_user.avatar_small_blob
        else:
            avatar = await download_small_avatar(chat_id, context)
            if avatar:
                db_user.avatar_small_blob = avatar
                dao.commit()
            return avatar
    else:
        return await download_small_avatar(chat_id, context)


async def download_small_avatar(
    chat_id: int, context: ContextTypes.DEFAULT_TYPE
) -> bytes | None:
    try:
        avatar_photo = (await context.bot.get_chat(chat_id=chat_id)).photo
        if not avatar_photo:
            return None
        avatar = await (await avatar_photo.get_small_file()).download_as_bytearray()
        avatar = bytes(avatar)
        return avatar
    except Exception as err:
        logger.error(
            f"{err.__class__.__name__}: {err} happend when getting small avatar"
        )
        return None


def get_chat_waifu_relationships(
    chat: Chat | ChatData,
) -> Generator[tuple[int, int], None, None]:
    # relationships: a generator that yields (int, int) for (user_id, waifu_id)
    members = dao.get_chat_members(chat)
    for member in members:
        waifu = dao.get_user_waifu_in_chat(member, chat)
        if waifu:
            yield (member.id, waifu.id)


def get_chat_waifu_info_dict(
    chat: Chat | ChatData,
) -> dict[int, int]:
    # waifu_info_dict: a dict that maps user_id to waifu_id
    waifu_info_dict = {}
    for user_id, waifu_id in get_chat_waifu_relationships(chat):
        waifu_info_dict[user_id] = waifu_id
    return waifu_info_dict


async def verify_user_is_chat_admin(
    user: User, chat: Chat, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    """
    验证用户是否是群管理员

    :return: bool
    """
    if chat.type == ChatType.PRIVATE:
        return False
    admins = await context.bot.get_chat_administrators(chat_id=chat.id)
    if user.id not in [admin.user.id for admin in admins]:
        return False
    return True


async def verify_user_can_manage_bot(
    user: User, chat: Chat, update: Update, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    """
    验证用户是否有在该聊天中管理bot的权限
    可以管理bot的人包括：群主（和匿名管理员）、bot的全局管理员、在群中被群主授权的bot管理员

    :return: bool
    """
    if chat.type == ChatType.PRIVATE:
        return False
    if (
        user.id in settings.owners
        or user.id == ChatID.ANONYMOUS_ADMIN
        or dao.get_user_is_bot_global_admin(user)
        or dao.get_user_is_bot_admin_in_chat(user, chat)
    ):
        return True
    try:
        chat_member = await context.bot.get_chat_member(
            chat_id=chat.id, user_id=user.id
        )
        if chat_member.status == ChatMemberStatus.OWNER:
            return True
        if update.callback_query:
            await update.callback_query.answer(
                "你没有执行此操作的权限", show_alert=False, cache_time=10
            )
    except Exception as err:
        logger.warning(f"{err.__class__.__name__}: {err}")
        if update.callback_query:
            await update.callback_query.answer(
                (
                    "无法获取成员信息, 如果开启了隐藏群成员, 请赋予 bot 管理员权限\n"
                    f"错误信息: {err.__class__.__name__}: {err}"
                ),
                show_alert=True,
                cache_time=5,
            )
        return False
    return False


def get_message_common_link(message: Message) -> str:
    chat = message.chat
    if chat.username:
        link = f"https://t.me/c/{str(chat.id).removeprefix('-100')}/{message.id}"
    else:
        link = message.link
    return link


def parse_message_link(link: str) -> tuple[int, int]:
    split_link = link.split("/")
    try:
        chat_id = int("-100" + split_link[-2])
        message_id = int(split_link[-1])
    except ValueError:
        logger.error(f"无法解析链接: {link}")
        return None, None
    return chat_id, message_id
