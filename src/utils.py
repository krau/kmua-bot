import io
import random
from operator import attrgetter
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont
from pilmoji import Pilmoji
from telegram import (
    Update,
)
from telegram.ext import ContextTypes

from .model import MemberData


def random_unit(probability: float) -> bool:
    """
    以probability的概率返回True

    :param probability: 概率
    :return: bool
    """
    assert 0 <= probability <= 1, "参数probability应该在[0,1]之间"
    return random.uniform(0, 1) < probability


async def generate_quote_img(
    avatar: bytearray, text: str, name: str, width: int = 1280, height: int = 640
) -> bytes:
    """
    生成引用图片

    :param avatar: 头像图片
    :param text: 引用内容
    :param width: 图片宽度
    :param height: 图片高度
    :return: 图片
    """
    color_bg = (34, 34, 32, 255)
    img = Image.new("RGBA", (width, height), color_bg)
    # 删除换行
    text = text.replace("\n", " ")
    # 加载头像
    avatar = Image.open(io.BytesIO(avatar))
    avatar = avatar.resize((640, 640), Image.ANTIALIAS)
    font_path = str(Path(__file__).resolve().parent.parent / "resource" / "TsukuA.ttc")
    font_size = 60
    font = ImageFont.truetype(font_path, font_size)
    text_width, text_height = font.getsize(text)
    text_x = int(width / 2) + int((width / 2 - text_width) / 2)
    text_y = int((height - text_height) / 2)
    text_list = [text[i : i + 10] for i in range(0, len(text), 10)]
    new_text_height = font_size * len(text_list)
    new_text_width = max([font.getsize(x)[0] for x in text_list])
    text_x = int(width / 2) + int((width / 2 - new_text_width) / 2)
    text_y = int((height - new_text_height) / 2)

    shadow_radius = 20
    shadow_img = Image.new(
        "RGBA",
        (width + shadow_radius * 2, height + shadow_radius * 2),
        color=(0, 0, 0, 0),
    )
    shadow_draw = ImageDraw.Draw(shadow_img)
    shadow_color = (0, 0, 0, 50)
    shadow_draw.rectangle(
        (shadow_radius, shadow_radius, width + shadow_radius, height + shadow_radius),
        fill=shadow_color,
        outline=None,
        width=0,
    )
    shadow_img = shadow_img.filter(ImageFilter.GaussianBlur(shadow_radius))

    draw = ImageDraw.Draw(img)
    # 粘贴背景
    draw.rectangle((int(width / 2), 0, width, height), fill=color_bg)
    with Pilmoji(img) as pilmoji:
        for i in range(len(text_list)):
            pilmoji.text(
                (text_x, text_y + i * font_size),
                text=text_list[i],
                fill=(255, 255, 252),
                font=font,
                align="center",
                emoji_position_offset=(0, 20),
            )
    # 在右下角粘贴名字
    name_font_size = 32
    name_font = ImageFont.truetype(font_path, name_font_size)
    name_width, name_height = name_font.getsize(name)
    name_x = int(width / 2) + int((width / 2 - name_width) / 2) + 80
    name_y = int(height - name_height) - 20
    with Pilmoji(img) as pilmoji:
        pilmoji.text(
            (name_x, name_y),
            text=f"—— {name}",
            font=name_font,
            fill=(255, 255, 252),
            align="center",
        )
    # 粘贴头像
    img.paste(avatar, (0, 0))
    # 粘贴阴影
    img.paste(shadow_img, (-shadow_radius, -shadow_radius), shadow_img)

    img_byte_arr = io.BytesIO()
    img = img.convert("RGB")
    img.save(img_byte_arr, format="JPEG")
    img_byte_arr = img_byte_arr.getvalue()
    return img_byte_arr


async def message_recorder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    this_user = update.effective_user
    this_chat = update.effective_chat
    if not this_user:
        return
    if this_user and this_user.is_bot:
        context.user_data.clear()
        if this_chat.type != "private" and context.chat_data.get("members_data"):
            if context.chat_data["members_data"].get(this_user.id):
                del context.chat_data["members_data"][this_user.id]
        return
    this_message = update.effective_message
    if this_message.is_automatic_forward:
        return
    if this_message.reply_to_message:
        return
    if context.user_data.get("msg_num", None):
        context.user_data.pop("msg_num", None)
        context.user_data.pop("pm_kmua_num", None)
        context.user_data.pop("group_msg_num", None)
        context.chat_data.pop("msg_num", None)
        context.user_data.pop("text_num", None)
        context.user_data.pop("photo_num", None)
        context.user_data.pop("sticker_num", None)
        context.user_data.pop("voice_num", None)
        context.user_data.pop("video_num", None)
        context.user_data.pop("document_num", None)
    if this_chat.type != "private":
        if not context.chat_data.get("members_data", None):
            context.chat_data["members_data"] = {}
        if not context.chat_data["members_data"].get(this_user.id, None):
            member_data_obj = MemberData(
                name=this_user.full_name, id=this_user.id, msg_num=0, quote_num=0
            )
            context.chat_data["members_data"][this_user.id] = member_data_obj
        context.chat_data["members_data"][this_user.id].msg_num += 1


def sort_topn_bykey(data: dict, n: int, key: str) -> list:
    """
    将字典按照指定的key排序，取前n个

    :param data: 字典
    :param n: 取前n个
    :param key: 指定的key
    :return: 排序后的列表
    """
    return sorted(data.values(), key=attrgetter(key), reverse=True)[:n]
