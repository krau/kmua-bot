from dataclasses import dataclass
from enum import IntEnum, StrEnum
from typing import Any


class GiftRarity(IntEnum):
    COMMON = 1
    ENCHANTED = 2
    RARE = 3
    EPIC = 4
    LEGENDARY = 5


RARETY_DISPLAY_NAMES: dict[GiftRarity, str] = {
    GiftRarity.COMMON: "凡芽",
    GiftRarity.ENCHANTED: "灵植",
    GiftRarity.RARE: "仪花",
    GiftRarity.EPIC: "秘种",
    GiftRarity.LEGENDARY: "禁华",
}


def get_rarity_display_name(rarity: int) -> str:
    try:
        rarity_enum = GiftRarity(rarity)
    except ValueError:
        return "未知"
    return RARETY_DISPLAY_NAMES.get(rarity_enum, "未知")


class GiftID(StrEnum):
    SEVERED_GRASS_SILENCE = "severed_grass_silence"
    VOW_LOTUS_SEAL = "vow_lotus_seal"
    AMARANTH_HEART_LAMP = "amaranth_heart_lamp"
    OTHERWORLDLY_FLOWER = "otherworldly_flower"


GIFT_DISPLAY_NAMES: dict[GiftID, str] = {
    GiftID.SEVERED_GRASS_SILENCE: "默断之草",
    GiftID.VOW_LOTUS_SEAL: "誓印之莲",
    GiftID.AMARANTH_HEART_LAMP: "苋色心灯",
    GiftID.OTHERWORLDLY_FLOWER: "异界之花",
}


def get_display_name(gift_id: GiftID) -> str:
    return GIFT_DISPLAY_NAMES.get(gift_id, "Otherworldly Flower")


@dataclass(frozen=True)
class Gift:
    id: GiftID
    description: str
    price: int
    effects: dict[str, Any]
    consumable: bool = True
    comment: str = ""


ALL_GIFTS: dict[GiftID, Gift] = {
    GiftID.SEVERED_GRASS_SILENCE: Gift(
        id=GiftID.SEVERED_GRASS_SILENCE,
        description="花色褪尽, 草根断离; 记忆并非被抹去, 只是再也无人能够指认它曾经存在",
        price=4721,
        effects={},
        consumable=True,
        comment="清空记忆",
    ),
    GiftID.VOW_LOTUS_SEAL: Gift(
        id=GiftID.VOW_LOTUS_SEAL,
        description="以莲为誓，心如止水；愿君安然，无惧风浪",
        price=2473,
        effects={"duration": 7200, "passivation": 3.7},
        consumable=True,
        comment="在一段时间内显著避免好感度变动",
    ),
    GiftID.AMARANTH_HEART_LAMP: Gift(
        id=GiftID.AMARANTH_HEART_LAMP,
        description="灯火未央，心之所向；愿君前路，光明常在",
        price=983,
        effects={"add_affection": 263, "duration": 1800},
        consumable=True,
        comment="短暂地大幅提升好感度数值",
    ),
}

OTHERWORLDLY_FLOWER = Gift(
    id=GiftID.OTHERWORLDLY_FLOWER,
    description="本不应存在于此的花朵",
    price=9973,
    effects={},
    consumable=True,
    comment="异常礼物, 不应出现",
)


def get_gift_by_id(gift_id: GiftID) -> Gift:
    gift = ALL_GIFTS.get(gift_id)
    if gift is None:
        return OTHERWORLDLY_FLOWER
    return gift


def list_all_gifts() -> list[Gift]:
    return list(ALL_GIFTS.values())


def list_affordable_gifts(coins: int) -> list[Gift]:
    return [gift for gift in ALL_GIFTS.values() if gift.price <= coins]
