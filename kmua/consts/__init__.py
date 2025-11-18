from pathlib import Path

REPO_URL = "https://github.com/krau/kmua-bot/"
DOCS_URL = "https://kmua.unv.app"

RESOURCES_DIRNAME = "resources"

_file_path = Path(__file__).parent.parent.resolve()
_resources_path = _file_path / RESOURCES_DIRNAME

DEFAULT_SMALL_AVATAR_PATH = _resources_path / "Akkarin_small.png"
DEFAULT_BIG_AVATAR_PATH = _resources_path / "Akkarin.jpg"

QUOTE_FONT_PATH = _resources_path / "TsukuA.ttc"

QUOTE_BASE_IMG_PATH = _resources_path / "quote_base.png"
WORD_DICT_INTERNAL_PATH = _resources_path / "word_dicts"
MANOMEME_PATH = _resources_path / "manomeme"
