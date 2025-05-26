import io

import pyrogram
from PIL import Image, ImageFont
from pilmoji import Pilmoji

from kmua import common, consts


async def send_quote(
    client: pyrogram.Client,
    chat_id: int,
    message: pyrogram.types.Message,
    user: pyrogram.types.User | pyrogram.types.Chat,
) -> str | None:
    """generate and send a quote message.

    Arguments:
        client -- pyrogram.Client
        chat_id -- chat id to send the quote
        message -- quote message
        user -- quote user

    Returns:
        the image file_id if sent successfully, otherwise None
    """
    if not message.text or len(message.text) > 200:
        return None
    avatar = await common.ChatAvatar(user.id).get_or_default_bytes(True)
    await client.send_chat_action(chat_id, pyrogram.enums.ChatAction.UPLOAD_PHOTO)
    quote_img = await _gen_quote_img(
        avatar,
        message.text,
        (user.username or user.full_name)
        if isinstance(user, pyrogram.types.User)
        else (user.username or user.title),
    )
    sent = await client.send_photo(chat_id=chat_id, photo=io.BytesIO(quote_img))
    return sent.photo.file_id


async def gen_quote_img(avatar: bytes, text: str, name: str) -> bytes:
    text = text.replace("\n", " ")

    img_width, img_height = 1200, 640
    font_size = 42
    name_font_size = 24

    font = ImageFont.truetype(consts.QUOTE_FONT_PATH, font_size)
    name_font = ImageFont.truetype(consts.QUOTE_FONT_PATH, name_font_size)
    base_img = Image.open(consts.QUOTE_BASE_IMG_PATH)
    avatar_img = Image.open(io.BytesIO(avatar))

    img = Image.new("RGBA", (img_width, img_height), (255, 255, 255, 0))
    img.paste(avatar_img, (0, 0))
    img.paste(base_img, (0, 0), base_img)

    text_list = [text[i : i + 18] for i in range(0, len(text), 18)]
    new_text_height = font_size * len(text_list)
    new_text_width = max(font.getbbox(x)[2] - font.getbbox(x)[0] for x in text_list)
    text_x = 540 + int((560 - new_text_width) / 2)
    text_y = int((img_height - new_text_height) / 2)

    with Pilmoji(img) as pilmoji:
        for i, v in enumerate(text_list):
            pilmoji.text(
                (text_x, text_y + i * font_size),
                text=v,
                fill=(255, 255, 252),
                font=font,
                align="center",
                emoji_position_offset=(0, 12),
            )

    left, top, right, bottom = name_font.getbbox(name)
    name_width = right - left
    name_height = bottom - top
    name_x = 600 + int((560 - name_width) / 2)
    name_y = img_height - name_height - 20

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
    img_byte_arr.seek(0)
    return img_byte_arr.getvalue()


def get_message_origin(
    message: pyrogram.types.Message,
) -> pyrogram.types.User | pyrogram.types.Chat | None:
    if origin := message.forward_origin:
        match origin.type:
            case pyrogram.enums.MessageOriginType.USER:
                return origin.sender_user
            case pyrogram.enums.MessageOriginType.CHANNEL:
                return origin.chat
            case pyrogram.enums.MessageOriginType.CHAT:
                return origin.sender_chat
    return message.sender_chat or message.from_user


def get_msg_link(message: pyrogram.types.Message) -> str:
    try:
        chat = message.chat
        link = f"https://t.me/c/{str(chat.id).removeprefix('-100')}/{message.id}"
        return link
    except Exception as e:
        return None
