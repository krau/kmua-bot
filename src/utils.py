import io
import os
import random
import re
from itertools import chain
from operator import attrgetter
from pathlib import Path
from typing import Generator

from PIL import Image, ImageFont
from pilmoji import Pilmoji
from telegram import (
    Update,
)
from telegram import Chat
from telegram.constants import ChatType
from telegram.ext import ContextTypes
from telegram.constants import ChatID

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


async def message_recorder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    this_user = update.effective_user
    this_chat = update.effective_chat
    this_message = update.effective_message
    if not this_user or not this_chat:
        return
    if this_user.is_bot or this_user.id in fake_users_id:
        return
    if this_message.reply_to_message:
        return
    db_user = dao.add_user(this_user)
    if this_chat.type == ChatType.GROUP or this_chat.type == ChatType.SUPERGROUP:
        db_chat = dao.add_chat(this_chat)
        if db_user not in db_chat.members:
            db_chat.members.append(db_user)
            dao.commit()


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
