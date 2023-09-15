import os
import pathlib
import random
import re
from operator import attrgetter
import glob
from ..logger import logger
import json

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)


back_home_markup = InlineKeyboardMarkup(
    [
        [
            InlineKeyboardButton("Back", callback_data="back_home"),
        ]
    ]
)


def random_unit(probability: float) -> bool:
    """
    以probability的概率返回True

    :param probability: 概率
    :return: bool
    """
    assert 0 <= probability <= 1, "参数probability应该在[0,1]之间"
    return random.uniform(0, 1) < probability


def sort_topn_bykey(data: dict, n: int, key: str) -> list:
    """
    将字典按照指定的key排序，取前n个

    :param data: 字典
    :param n: 取前n个
    :param key: 指定的key
    :return: 排序后的列表
    """
    return sorted(data.values(), key=attrgetter(key), reverse=True)[:n]


def parse_arguments(text: str) -> list[str]:
    pattern = r'"([^"]*)"|([^ ]+)'
    arguments = re.findall(pattern, text)
    parsed_arguments = [group[0] or group[1] for group in arguments]

    return parsed_arguments


def _load_word_dict():
    word_dict_path_internal = (
        pathlib.Path(__file__).parent.parent.parent / "resource" / "word_dicts"
    )
    word_dict_path_user = (
        pathlib.Path(__file__).parent.parent.parent / "data" / "word_dicts"
    )
    word_dict = {}
    for file in glob.glob(f"{word_dict_path_internal}" + r"/*.json"):
        logger.debug(f"加载内置词库: {file}")
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
            logger.debug(f"加载用户词库: {file}")
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
    logger.debug(f"词库加载完成, 共加载词条: {len(word_dict)}")
    return word_dict


word_dict = _load_word_dict()
ohayo_word = word_dict.get("早", ["早安", "早上好", "早上好呀", "早上好哦"])
oyasumi_word = word_dict.get("晚安", ["晚安", "晚安呀", "晚安哦", "晚安喵"])
