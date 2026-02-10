import glob

import orjson
from anyio import Path

from kmua.logger import logger

_word_dict_cache: dict[str, list[str]] | None = None


def _load_words() -> dict[str, list[str]]:
    """加载词库文件"""
    internal_path = Path(__file__).parent / "word_dicts"
    words = {}
    logger.debug(f"loading word dicts from {internal_path}")
    for file in glob.glob(f"{internal_path}" + r"/*.json"):
        try:
            with open(file, encoding="utf-8") as f:
                for k, v in orjson.loads(f.read()).items():
                    if k in words:
                        words[k].extend(v)
                    else:
                        words[k] = v
        except Exception as e:
            logger.error(
                f"loading word dict failed: {file}: {e.__class__.__name__}: {e}"
            )
            continue
    return words


def get_word_dict() -> dict[str, list[str]]:
    """
    获取词库，按需加载并缓存
    """
    global _word_dict_cache
    if _word_dict_cache is None:
        _word_dict_cache = _load_words()
    return _word_dict_cache
