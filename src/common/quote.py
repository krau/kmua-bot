import io
import os
from pathlib import Path

from PIL import Image, ImageFont
from pilmoji import Pilmoji


async def generate_quote_img(avatar: bytes, text: str, name: str) -> bytes:
    text = text.replace("\n", " ")
    font_path = str(
        Path(__file__).resolve().parent.parent.parent / "resource" / "TsukuA.ttc"
    )
    font_size = 42
    font = ImageFont.truetype(font_path, font_size)
    base_img = Image.open(
        os.path.join(
            Path(os.path.dirname(__file__)).parent.parent, "resource", "base.png"
        )
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
