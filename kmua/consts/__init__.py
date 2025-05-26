from pathlib import Path

REPO_URL = "https://github.com/krau/kmua-bot/"
DOCS_URL = "https://kmua.unv.app"

RESOURCES_DIRNAME = "resources"

DEFAULT_SMALL_AVATAR_PATH = (
    Path(__file__).parent.parent.resolve() / RESOURCES_DIRNAME / "Akkarin_small.png"
)
DEFAULT_BIG_AVATAR_PATH = (
    Path(__file__).parent.parent.resolve() / RESOURCES_DIRNAME / "Akkarin.jpg"
)

QUOTE_FONT_PATH = (
    Path(__file__).parent.parent.resolve() / RESOURCES_DIRNAME / "TsukuA.ttc"
)

QUOTE_BASE_IMG_PATH = (
    Path(__file__).parent.parent.resolve() / RESOURCES_DIRNAME / "quote_base.png"
)
WORD_DICT_INTERNAL_PATH = (
    Path(__file__).parent.parent.resolve() / RESOURCES_DIRNAME / "word_dicts"
)
