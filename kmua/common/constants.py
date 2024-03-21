from pathlib import Path

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from kmua.config import data_dir, settings

QUOTE_PAGE_SIZE = 5
PAGE_JUMP_SIZE = 20

DETAIL_HELP_URL = "https://krau.github.io/kmua-bot/"
OPEN_SOURCE_URL = "https://github.com/krau/kmua-bot/"

BACK_HOME_MARKUP = InlineKeyboardMarkup(
    [
        [
            InlineKeyboardButton("返回", callback_data="back_home"),
        ]
    ]
)

DB_PATH = (
    Path(data_dir / settings.get("db_url", "sqlite:///./data/kmua.db").split("/")[-1])
    if settings.get("db_url").startswith("sqlite")
    else None
)
