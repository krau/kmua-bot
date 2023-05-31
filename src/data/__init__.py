import json
import pathlib
import glob
import os
from ..logger import logger


def _load_word_dict():
    word_dict_path_internal = (
        pathlib.Path(__file__).parent.parent.parent / "resource" / "word_dicts"
    )
    word_dict_path_user = (
        pathlib.Path(__file__).parent.parent.parent / "data" / "word_dicts"
    )
    word_dict = {}
    for file in glob.glob(f"{word_dict_path_internal}" + r"/*.json"):
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
    if os.path.exists(word_dict_path_user):
        for file in glob.glob(f"{word_dict_path_user}" + r"/*.json"):
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
country = [
    "阿富汗",
    "中国",
    "日本",
    "韩国",
    "朝鲜",
    "越南",
    "缅甸",
    "美国",
    "加拿大",
    "英国",
    "法国",
    "德国",
    "阿根廷",
    "土耳其",
    "印度",
]
role = ["男孩子", "女孩子", "武装直升机", "TNT", "锟斤拷锟斤拷", "土豆", "xyn"]
birthplace = [
    "首都",
    "省会",
    "直辖市",
    "市区",
    "县城",
    "自治区",
    "农村",
    "乡村",
    "山村",
    "大学女厕所",
    "大学男厕所",
    "高中女厕所",
    "初中女厕所",
]
