from pathlib import Path

REPO_URL = "https://github.com/krau/kmua-bot/"
DOCS_URL = "https://kmua.unv.app"

# One quota credit represents this many billable model tokens. Billable tokens
# are already weighted (for example, a cache read may count at 10%), and the
# conversion rounds away from zero so a non-zero run never becomes free.
TOKENS_PER_CREDIT = 100


def token_units_to_credits(token_units: int) -> int:
    """Convert weighted token units to whole credits, rounding away from zero."""
    if token_units == 0:
        return 0
    magnitude = (abs(token_units) + TOKENS_PER_CREDIT - 1) // TOKENS_PER_CREDIT
    return -magnitude if token_units < 0 else magnitude


RESOURCES_DIRNAME = "resources"

_file_path = Path(__file__).parent.parent.resolve()
_resources_path = _file_path / RESOURCES_DIRNAME

DEFAULT_SMALL_AVATAR_PATH = _resources_path / "Akkarin_small.png"
DEFAULT_BIG_AVATAR_PATH = _resources_path / "Akkarin.jpg"

QUOTE_FONT_PATH = _resources_path / "TsukuA.ttc"

QUOTE_BASE_IMG_PATH = _resources_path / "quote_base.png"
WORD_DICT_INTERNAL_PATH = _resources_path / "word_dicts"
MANOMEME_PATH = _resources_path / "manomeme"
