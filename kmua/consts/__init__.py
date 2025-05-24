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
