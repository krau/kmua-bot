from dataclasses import dataclass

from pydantic import BaseModel
from pyrogram.client import Client as PyrogramClient
from pyrogram.types import Message


class MemoryAboutUser(BaseModel):
    Disposition: str | None  # 性格
    Interests: str | None  # 兴趣
    Doings: str | None  # 正在做的事情
    Works: str | None  # 工作内容
    Wishes: str | None  # 希望/愿望
    Worries: str | None  # 担忧/烦恼
    Skills: str | None  # 技能
    AttitudesToMe: str | None  # 对'我'的态度
    ExperiencesWithMe: str | None  # 和'我'相关的经历
    ExtraInfo: str | None  # 其他补充信息


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
