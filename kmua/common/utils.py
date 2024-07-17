import glob
import orjson
import os
import random
from pathlib import Path

from kmua.logger import logger


def random_unit(probability: float) -> bool:
    """
    以probability的概率返回True

    :param probability: 概率
    :return: bool
    """
    if probability < 0:
        return False
    if probability > 1:
        return True
    return random.uniform(0, 1) < probability


def _load_word_dict():
    word_dict_path_internal = Path(__file__).parent.parent / "resource" / "word_dicts"
    word_dict_path_user = Path(__file__).parent.parent.parent / "data" / "word_dicts"
    word_dict = {}
    for file in glob.glob(f"{word_dict_path_internal}" + r"/*.json"):
        logger.debug(f"loading word dict: {file}")
        try:
            with open(file, "r", encoding="utf-8") as f:
                for k, v in orjson.loads(f.read()).items():
                    if k in word_dict:
                        word_dict[k].extend(v)
                    else:
                        word_dict[k] = v
        except Exception as e:
            logger.error(
                f"loading word dict failed: {file}: {e.__class__.__name__}: {e}"
            )
            continue
    if os.path.exists(word_dict_path_user):
        for file in glob.glob(f"{word_dict_path_user}" + r"/*.json"):
            logger.debug(f"loading user word dict: {file}")
            try:
                with open(file, "r", encoding="utf-8") as f:
                    for k, v in orjson.loads(f.read()).items():
                        if k in word_dict:
                            word_dict[k].extend(v)
                        else:
                            word_dict[k] = v
            except Exception as e:
                logger.error(
                    f"loading user word dict failed: {file}: {e.__class__.__name__}: {e}"
                )
                continue
    logger.debug(f"successfully loaded word dict, total {len(word_dict)} words")
    return word_dict


word_dict = _load_word_dict()
ohayo_word = word_dict.get("早", ["早安", "早上好", "早上好呀", "早上好哦"])
oyasumi_word = word_dict.get("晚安", ["晚安", "晚安呀", "晚安哦", "晚安喵"])

loading_word = [
    "少女祈祷中",
    "少女折寿中",
    "喵喵喵喵中",
    "色图绘制中",
    "请坐和放宽",
    "海内存知己, 天涯若比邻",
    "这可能需要1点时间",
    "这可能需要2点时间",
    "这可能需要3点时间",
    "这可能需要几个世纪",
    "请勿关闭电脑",
    "请勿关闭手机",
    "快到我床上中",
    "床上贴贴中",
    "床上睡觉中",
    "色图发送中",
    "少女摇补子中",
    "少女玩郊狼中",
    "少女伪街中",
    "少女炼铜中",
    "少女抽卡中",
    "少女更新蒸汽平台中",
    "少女写bug中",
    "少女改bug中",
    "少女吃麦当劳中",
    "少女面姬中",
    "少女抱抱中",
    "少女贴贴中",
    "少女摸摸中",
    "少女0721中",
    "少女喵喵中",
    "少女看番中",
    "Loading...",
    "少女离家出走中",
    "少女睡觉中",
    "少女熬夜中",
    "少女 ALL PERFECT 中",
    "少女粉绝赞中",
    "少女 FULL COMBO 中",
    "少女吹风扇中",
    "少女比心心中",
    "正在 cos 猫娘",
    "少女原神中",
    "玩命加载中",
    "QAQ中",
    "qwq中",
    "ovo中",
    "少女吃糖中",
    "少女报菜名中",
    "少女呜呜中",
    "少女😣中",
    "少女爱发电中",
    "少女围着你转中",
    "少女艾草中",
    "少女打📐中",
    "少女露奶子中",
    "少女鹿管中",
    "少女鹿馆中",
]
