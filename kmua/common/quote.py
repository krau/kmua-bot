import io
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
    result_id = uuid4()
    result = InlineQueryResultCachedPhoto(
        id=result_id,
        photo_file_id=quote.img,
        title=quote.text,
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
    result_id = uuid4()
    quote_user_name = quote.user.full_name if quote.user else "<数据丢失>"
    quote_chat_title = quote.chat.title if quote.chat else "<数据丢失>"
    qer_user = dao.get_user_by_id(quote.qer_id)
    qer_user_name = qer_user.full_name if qer_user else "<数据丢失>"
    result = InlineQueryResultArticle(
        id=result_id,
        title=quote.text,
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


def generate_quote_img(avatar: bytes, text: str, name: str) -> bytes:
    text = text.replace("\n", " ")
    script_dir = Path(__file__).resolve().parent
    font_path = str(script_dir.parent / "resource" / "TsukuA.ttc")
    base_img_path = str(script_dir.parent / "resource" / "base.png")

    img_width, img_height = 1200, 630
    font_size = 42
    name_font_size = 24

    font = ImageFont.truetype(font_path, font_size)
    name_font = ImageFont.truetype(font_path, name_font_size)
    base_img = Image.open(base_img_path)
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
