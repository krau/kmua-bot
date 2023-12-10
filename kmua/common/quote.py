import io
import os
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageFont
from pilmoji import Pilmoji
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQueryResultArticle,
    InlineQueryResultCachedPhoto,
    InputTextMessageContent,
)

from kmua import dao
from kmua.models.models import Quote

qer_quote_manage_button = [
    InlineKeyboardButton(
        "看看别人的",
        callback_data="qer_quote_manage",
    )
]

user_quote_manage_button = [
    InlineKeyboardButton(
        "看看我的",
        callback_data="user_quote_manage",
    )
]


no_quote_markup = InlineKeyboardMarkup(
    [
        qer_quote_manage_button,
        [
            InlineKeyboardButton(
                "返回",
                callback_data="back_home",
            )
        ],
    ],
)


def get_user_quote_navigation_buttons(page: int) -> list[InlineKeyboardButton]:
    navigation_buttons = [
        InlineKeyboardButton(
            "上一页",
            callback_data=f"user_quote_manage {page - 1}",
        ),
        InlineKeyboardButton(
            "返回",
            callback_data="back_home",
        ),
        InlineKeyboardButton(
            "下一页",
            callback_data=f"user_quote_manage {page + 1}",
        ),
    ]
    return navigation_buttons


def get_qer_quote_navigation_buttons(page: int) -> list[InlineKeyboardButton]:
    navigation_buttons = [
        InlineKeyboardButton(
            "上一页",
            callback_data=f"qer_quote_manage {page - 1}",
        ),
        InlineKeyboardButton(
            "返回",
            callback_data="back_home",
        ),
        InlineKeyboardButton(
            "下一页",
            callback_data=f"qer_quote_manage {page + 1}",
        ),
    ]
    return navigation_buttons


def get_inline_query_result_cached_photo(quote: Quote) -> InlineQueryResultCachedPhoto:
    if not quote.img:
        return None
    id = uuid4()
    result = InlineQueryResultCachedPhoto(
        id=id,
        photo_file_id=quote.img,
        title=quote.text[:10],
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "Source",
                        url=quote.link,
                    )
                ]
            ]
        ),
    )
    return result


def get_inline_query_result_article(quote: Quote) -> InlineQueryResultArticle:
    id = uuid4()
    quote_user_name = quote.user.full_name if quote.user else "<数据丢失>"
    quote_chat_title = quote.chat.title if quote.chat else "<数据丢失>"
    qer_user = dao.get_user_by_id(quote.qer_id)
    qer_user_name = qer_user.full_name if qer_user else "<数据丢失>"
    result = InlineQueryResultArticle(
        id=id,
        title=quote.text[:10],
        description=f"""
For {quote_user_name} in {quote_chat_title}
Create at {datetime.strftime(quote.created_at, '%Y-%m-%d %H:%M:%S')} by {qer_user_name}
""",
        input_message_content=InputTextMessageContent(quote.text),
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "Source",
                        url=quote.link,
                    )
                ]
            ]
        ),
    )
    return result


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
