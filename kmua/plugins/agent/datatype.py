from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from powermem import AsyncMemory
from pydantic import BaseModel, Field
from pydantic_ai import ModelMessage
from pyrogram.client import Client as PyrogramClient
from pyrogram.types import Message


class ChatMemoryy(BaseModel):
    disposition: list[str] | str | None = Field(description="性格")
    interests: list[str] | str | None = Field(description="兴趣爱好")
    doings: list[str] | str | None = Field(description="正在做的事情")
    works: list[str] | str | None = Field(description="工作/职业")
    wishes: list[str] | str | None = Field(description="愿望/目标")
    worries: list[str] | str | None = Field(description="担忧/烦恼")
    skills: list[str] | str | None = Field(description="技能/专长")
    attitudes_to_you: list[str] | str | None = Field(description="对你的态度")
    experiences_with_you: list[str] | str | None = Field(description="与你的经历")
    extra_info: list[str] | str | None = Field(description="其他补充信息, 若无可不填")

    def to_text(self, is_group_chat: bool = False) -> str:
        parts = []
        if self.disposition:
            parts.append(f"性格: {';'.join(self.disposition)}")
        if self.attitudes_to_you:
            parts.append(f"对你的态度: {';'.join(self.attitudes_to_you)}")

        # 仅在私聊时输出完整信息
        if not is_group_chat:
            if self.interests:
                parts.append(f"兴趣爱好: {';'.join(self.interests)}")
            if self.doings:
                parts.append(f"正在做的事情: {';'.join(self.doings)}")
            if self.works:
                parts.append(f"工作/职业: {';'.join(self.works)}")
            if self.wishes:
                parts.append(f"愿望/目标: {';'.join(self.wishes)}")
            if self.worries:
                parts.append(f"担忧/烦恼: {';'.join(self.worries)}")
            if self.skills:
                parts.append(f"技能/专长: {';'.join(self.skills)}")
            if self.experiences_with_you:
                parts.append(f"与你的经历: {';'.join(self.experiences_with_you)}")
            if self.extra_info:
                parts.append(f"其他补充信息: {';'.join(self.extra_info)}")
        return "\n".join(parts)


class AffectionOption(StrEnum):
    INCREASE = "increase"
    DECREASE = "decrease"
    NO_CHANGE = "no_change"


class AffectionChangeAmplitude(StrEnum):
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"


# nested models fail ollama validation: https://github.com/pydantic/pydantic-ai/issues/607


class UserMemoryResult(BaseModel):
    disposition: str | None = Field(description="性格")
    interests: str | None = Field(description="兴趣爱好")
    doings: str | None = Field(description="正在做的事情")
    works: str | None = Field(description="工作/职业")
    wishes: str | None = Field(description="愿望/目标")
    worries: str | None = Field(description="担忧/烦恼")
    skills: str | None = Field(description="技能/专长")
    attitudes_to_model: str | None = Field(
        description="对聊天中的AI助手的态度, 若消息记录中没有AI助手的则保持不变"
    )
    experiences_with_model: str | None = Field(
        description="与聊天中的AI助手的经历, 若消息记录中没有AI助手的则保持不变"
    )
    extra_info: str | None = Field(description="其他补充信息, 若无可不填")
    affection_option: str = Field(
        description="好感度变化选项, 枚举值 increase,decrease,no_change"
    )
    affection_change_amplitude: str | None = Field(
        description="好感度变化幅度, 枚举值 small,medium,large"
    )

    def get_memory(self) -> ChatMemoryy:
        return ChatMemoryy(
            disposition=self.disposition,
            interests=self.interests,
            doings=self.doings,
            works=self.works,
            wishes=self.wishes,
            worries=self.worries,
            skills=self.skills,
            attitudes_to_you=self.attitudes_to_model,
            experiences_with_you=self.experiences_with_model,
            extra_info=self.extra_info,
        )

    def get_affection_change(self) -> int:
        affection_change: int = 0
        affection_option = AffectionOption(self.affection_option)
        affection_amplitude = None
        if self.affection_change_amplitude is not None:
            affection_amplitude = AffectionChangeAmplitude(
                self.affection_change_amplitude
            )
        match affection_option:
            case AffectionOption.INCREASE:
                if affection_amplitude is not None:
                    match affection_amplitude:
                        case AffectionChangeAmplitude.SMALL:
                            affection_change = 10
                        case AffectionChangeAmplitude.MEDIUM:
                            affection_change = 18
                        case AffectionChangeAmplitude.LARGE:
                            affection_change = 30
            case AffectionOption.DECREASE:
                if affection_amplitude is not None:
                    match affection_amplitude:
                        case AffectionChangeAmplitude.SMALL:
                            affection_change = -10
                        case AffectionChangeAmplitude.MEDIUM:
                            affection_change = -18
                        case AffectionChangeAmplitude.LARGE:
                            affection_change = -30
        return affection_change


class EndTurn(BaseModel):
    reason: str | None


@dataclass
class AskUserOutput:
    """Returned when ask_user output function fires — signals runner to stop silently."""

    question: str


@dataclass
class ContextDeps:
    client: PyrogramClient
    user_id: int
    chat_id: int
    message: Message
    instructions: str = ""
    powermemory: AsyncMemory | None = None
    multimodal_model: Any | None = None
    history: list[ModelMessage] = field(default_factory=list)
    tools_called_this_turn: set[str] = field(default_factory=set)


@dataclass
class UserData:
    user_id: int
    full_name: str
    username: str | None = None
    config: dict | None = None


@dataclass
class ContextInfo:
    user_data: UserData | None = None
    memory_about_user: ChatMemoryy | None = None
    append_prompt: str | None = None
    is_group_chat: bool = False

    def to_text(self) -> str:
        """The per-turn instruction block for additional_instructions: user
        profile, memory about the user, affection prompt. Time/msg/chat/reply
        metadata deliberately live in the per-message prompt blocks instead."""
        parts = []
        if self.user_data is not None:
            username = (
                f"@{self.user_data.username}" if self.user_data.username else "无"
            )
            parts.append(
                f"用户信息: 姓名: {self.user_data.full_name}, 用户名: {username}"
            )
        if self.memory_about_user is not None:
            memory_text = self.memory_about_user.to_text(
                is_group_chat=self.is_group_chat
            )
            if memory_text:
                parts.append(f"关于用户的记忆: ({memory_text})")
        if self.append_prompt:
            parts.append(f"附加提示: {self.append_prompt}")
        return "\n".join(parts)


@dataclass
class BotLastReply:
    message_id: int
    reply_to_user_id: int
    reply_to_message_id: int
    reply_text: str
    timestamp: float
    original_user_message: str = ""
    full_output: str = ""  # 可能分割成多条消息发送
