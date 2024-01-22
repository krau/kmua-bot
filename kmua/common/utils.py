import glob
import json
import os
import pathlib
import random
import re

from pyrogram.types import Chat, User

from kmua.logger import logger


def escape_markdown(text: str) -> str:
    escape_chars = r"\_*[]()~`>#+-=|{}.!"
    return re.sub(f"([{re.escape(escape_chars)}])", r"\\\1", text)


def mention_markdown(user: User | Chat) -> str:
    if isinstance(user, User):
        return f"[{escape_markdown(user.full_name)}](tg://user?id={user.id})"
    elif isinstance(user, Chat):
        return (
            f"[{escape_markdown(user.full_name)}](https://t.me/{user.username})"
            if user.username
            else f"[{escape_markdown(user.full_name)}](tg://user?id={user.id})"
        )
    else:
        raise TypeError(f"Unknown type {type(user)}")


def random_unit(probability: float) -> bool:
    """
    以probability的概率返回True

    :param probability: 概率
    :return: bool
    """
    assert 0 <= probability <= 1, "参数probability应该在[0,1]之间"
    return random.uniform(0, 1) < probability


def _load_word_dict():
    word_dict_path_internal = (
        pathlib.Path(__file__).parent.parent / "resource" / "word_dicts"
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
