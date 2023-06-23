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
role = ["男孩子", "女孩子", "武装直升机", "TNT", "土豆", "xyn", "猫猫", "狗子", "鼠鼠"]
birthplace = [
    "首都",
    "省会",
    "直辖市",
    "市区",
    "县城",
    "自治区",
    "农村",
    "山村",
    "大学",
    "职校"
]
suicide_fail_msg = [
    "楼层太低了, 没死透",
    "药的剂量不够",
    "药效不够强",
    "上吊的绳子不结实断了",
    "被晶哥救下并批评教育",
    "被学校提前发现并劝退",
    "被爹妈拦下, 骂你是个没良心的东西",
    "被同学提前发现, 并报告给了老师",
    "割腕到一半被送去医院了",
    "被杨院长发现, 绑在椅子上治疗了15天",
    "突然被群友叫去干饭了",
    "被老板发现, 辞退并罚款",
    "被人发现并送进急救, 然后被查看手机",
    "你现在不能睡觉, 周围有怪物在游荡",
    "你想起来自己电脑数据没销毁",
]
