from dataclasses import dataclass
from enum import IntEnum, StrEnum

from pydantic import BaseModel
from pyrogram.client import Client as PyrogramClient
from pyrogram.types import Message


class MemoryAboutUser(BaseModel):
    disposition: str | None  # 性格
    interests: str | None  # 兴趣
    doings: str | None  # 正在做的事情
    works: str | None  # 工作内容
    wishes: str | None  # 希望/愿望
    worries: str | None  # 担忧/烦恼
    skills: str | None  # 技能
    attitudes_to_me: str | None  # 对'我'的态度
    experiences_with_me: str | None  # 和'我'相关的经历
    extra_info: str | None  # 其他补充信息


class AffectionOption(StrEnum):
    INCREASE = "increase"
    DECREASE = "decrease"
    NO_CHANGE = "no_change"


class AffectionChangeAmplitude(IntEnum):
    SMALL = 1
    MEDIUM = 2
    LARGE = 3


class MemoryResult(BaseModel):
    result: MemoryAboutUser
    affection_option: AffectionOption
    affection_change_amplitude: AffectionChangeAmplitude | None = None


@dataclass
class ContextDeps:
    client: PyrogramClient
    user_id: int
    chat_id: int
    message: Message


@dataclass
class UserData:
    user_id: int
    full_name: str
    username: str | None = None
    config: dict | None = None


@dataclass
class ContextInfo:
    user_data: UserData | None = None
    msg_id: int | None = None
    current_time: str | None = None
    chat_type: str | None = None
    reply_to_msg_text: str | None = None
    reply_to_msg_id: int | None = None
    memory_about_user: MemoryAboutUser | None = None
