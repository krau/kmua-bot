import math
from pathlib import Path
from typing import List, Optional, Tuple

from sketchbook import (
    Drawer,
    DrawerRegion,
    PasteStyle,
    TextFitDrawer,
    TextStyle,
)

from kmua.consts import MANOMEME_PATH

from .models import Character, Option, Statement


def get_anan_base_image(face: Optional[str] = None) -> str:
    """Get the base image path for Anan's face

    Args:
        face (Optional[str], optional): The face type to be used. Available: 害羞, 生气, 病娇, 无语, 开心. Defaults to None.

    Returns:
        str: The path to the base image
    """
    if face is None:
        return str(MANOMEME_PATH / "anan/base.png")
    else:
        return str(MANOMEME_PATH / f"anan/{face}.png")


def draw_anan(text: str, face: Optional[str] = None) -> bytes:
    """Draw the image of what Anan says

    Args:
        text (str): The text to be drawn
        face (Optional[str], optional): The face type to be used. Available: 害羞, 生气, 病娇, 无语, 开心. Defaults to None.

    Returns:
        bytes: The image bytes of the drawn image
    """
    drawer = TextFitDrawer(
        base_image=get_anan_base_image(face),
        font=str(MANOMEME_PATH / "fonts/AaMingTianHuiYouHaoShiFaSheng-2.ttf"),
        overlay_image=str(MANOMEME_PATH / "anan/base_overlay.png"),
        region=DrawerRegion(100, 432, 100 + 319, 432 + 204),
    )
    image_bytes = drawer.draw(
        text=text,
        style=TextStyle(color=(0, 0, 0, 255)),
    )
    return image_bytes


def get_statement_image(statement: Statement) -> str:
    """Get the image path for a statement type

    Args:
        statement (Statement): The statement type

    Returns:
        str: The path to the statement image
    """
    mapping = {
        Statement.AGREEMENT: "agreement.png",
        Statement.DOUBT: "doubt.png",
        Statement.PURJURY: "perjury.png",
        Statement.REFUTATION: "refutation.png",
        Statement.MAGIC: "magic.png",
    }
    return str(MANOMEME_PATH / f"trial/{mapping[statement]}")


def get_option_coordinates(number: int) -> List[Tuple[int, int]]:
    """Get the coordinates for drawing options based on the number of options

    Args:
        number (int): The number of options

    Returns:
        List[Tuple[int, int]]: A list of (x, y) coordinates for each option
    """
    if number % 2 == 1:
        padding = min(
            286,
            (1080 - 364 - 216) // math.floor(number / 2)
            if math.floor(number / 2) != 0
            else 286,
            (-364 + 47) // math.ceil(-number / 2)
            if math.ceil(-number / 2) != 0
            else 286,
        )
        return [
            (29, 364 + padding * i)
            for i in range(math.ceil(-number / 2), math.floor(number / 2) + 1)
        ]
    else:
        padding = min(
            286.0,
            (1080 - 364 - 216) // (math.floor(number / 2) - 0.5),
            (-364 + 47) // (math.ceil(-number / 2) + 0.5),
        )
        return [
            (29, int(364 + padding * (i + 0.5)))
            for i in range(math.ceil(-number / 2), math.floor(number / 2))
        ]


def draw_trial(character: Character, options: List[Option]):
    """Draw the trial image for a character saying an option

    Args:
        character (Character): The character who is speaking
        options (List[Option]): The options being spoken

    Returns:
        bytes: The image bytes of the drawn image
    """
    # Bakcground and character
    drawer = Drawer(
        base_image=str(MANOMEME_PATH / "trial/black.png"),
        font=str(MANOMEME_PATH / "fonts/SourceHanSerifSC.otf"),
    )
    drawer = drawer.paste_image(
        str(MANOMEME_PATH / "trial/background.png"),
        region=DrawerRegion(0, 0, 1260, 1080),
        style=PasteStyle(keep_alpha=False),
    ).paste_image(
        str(
            MANOMEME_PATH
            / "trial"
            / ("ema.png" if character == Character.EMA else "hiro.png")
        ),
        region=DrawerRegion(667, 0, 1260, 1080),
        style=PasteStyle(keep_alpha=False),
    )

    # Options, texts, and statements
    coordinates = get_option_coordinates(len(options))
    for option, (x, y) in zip(options, coordinates):
        drawer = (
            drawer.paste_image(
                str(MANOMEME_PATH / "trial/option.png"),
                region=DrawerRegion(x, y, x + 802, y + 216),
                style=PasteStyle(keep_alpha=False),
            )
            .draw_text(
                text=option.text,
                region=DrawerRegion(x + 109, y + 32, x + 109 + 589, y + 32 + 150),
                style=TextStyle(
                    color=(39, 33, 30, 255),
                    bracket_color=(39, 33, 30, 255),
                    max_font_height=48,
                ),
            )
            .paste_image(
                get_statement_image(option.statement),
                region=DrawerRegion(x + 21, y - 41, x + 21 + 146, y - 41 + 126),
                style=PasteStyle(keep_alpha=False),
            )
        )

    return drawer.finish()
