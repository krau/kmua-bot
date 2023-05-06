import json
import pathlib
import glob
from ..logger import logger


def _load_word_dict():
    word_dict_path = (
        pathlib.Path(__file__).parent.parent.parent / "resource" / "word_dicts"
    )
    word_dict = {}
    for file in glob.glob(f"{word_dict_path}" + r"/*.json"):
        try:
            with open(file, "r") as f:
                for k, v in json.load(f).items():
                    if k in word_dict:
                        word_dict[k].extend(v)
                    else:
                        word_dict[k] = v
        except Exception as e:
            logger.error(f"加载词库失败: {file}: {e.__class__.__name__}: {e}")
            continue
    return word_dict


word_dict = _load_word_dict()
