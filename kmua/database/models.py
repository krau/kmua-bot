from dataclasses import asdict, dataclass
from datetime import datetime
from typing import List

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    String,
    func,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)


class Base(DeclarativeBase):
    pass


@dataclass
class UserConfig:
    lang: str = "zh-CN"
    coins: int = 144 * 16

    @classmethod
    def from_dict(cls, data: dict | None) -> "UserConfig":
        if data is None:
            return cls()
        return cls(lang=data.get("lang", "zh-CN"), coins=data.get("coins", 144 * 16))

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ChatConfig:
    waifu_enabled: bool = True
    delete_events_enabled: bool = False
    unpin_channel_pin_enabled: bool = False
    message_search_enabled: bool = False
    quote_probability: float = 0.001
    quote_pin_message: bool = True
    title_permissions: dict | None = None
    greeting: str | None = None
    ai_reply: bool = True
    setu_enabled: bool = True
    convert_b23_enabled: bool = True
    parse_artwork_enabled: bool = True
    lang: str = "zh-CN"

    @classmethod
    def from_dict(cls, data: dict | None) -> "ChatConfig":
        if data is None:
            return cls()
        return cls(
            waifu_enabled=data.get("waifu_enabled", True),
            delete_events_enabled=data.get("delete_events_enabled", False),
            unpin_channel_pin_enabled=data.get("unpin_channel_pin_enabled", False),
            message_search_enabled=data.get("message_search_enabled", False),
            quote_probability=data.get("quote_probability", 0.001),
            quote_pin_message=data.get("quote_pin_message", False),
            title_permissions=data.get("title_permissions", {}),
            greeting=data.get("greeting", None),
            ai_reply=data.get("ai_reply", True),
            setu_enabled=data.get("setu_enabled", True),
            convert_b23_enabled=data.get("convert_b23_enabled", False),
            parse_artwork_enabled=data.get("parse_artwork_enabled", True),
            lang=data.get("lang", "zh-CN"),
        )

    def to_dict(self) -> dict:
        return asdict(self)


class UserChatAssociation(Base):
    __tablename__ = "user_chat_association"

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("user_data.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
    chat_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("chat_data.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )

    waifu_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("user_data.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    is_bot_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    promoted_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class UserData(Base):
    __tablename__ = "user_data"

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=False,
        index=True,
    )

    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    full_name: Mapped[str] = mapped_column(String(256), nullable=False)

    avatar_big_id: Mapped[str | None] = mapped_column(
        String(256),
        nullable=True,
    )

    config: Mapped[dict] = mapped_column(
        JSON,
        default=lambda: asdict(UserConfig()),
    )
    is_married: Mapped[bool] = mapped_column(Boolean, default=False)
    married_waifu_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("user_data.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    waifu_mention: Mapped[bool] = mapped_column(Boolean, default=False)

    is_bot: Mapped[bool] = mapped_column(Boolean, default=False)
    is_real_user: Mapped[bool] = mapped_column(Boolean, default=True)
    is_bot_global_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
    update_avatar_at: Mapped[datetime | None] = mapped_column(
        DateTime(),
        nullable=True,
        default=None,
    )

    chats: Mapped[List["ChatData"]] = relationship(
        "ChatData",
        secondary="user_chat_association",
        back_populates="members",
        primaryjoin="UserData.id == UserChatAssociation.user_id",
        secondaryjoin="ChatData.id == UserChatAssociation.chat_id",
        lazy="noload",
    )

    quotes: Mapped[List["Quote"]] = relationship(
        "Quote",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="noload",
    )

    married_waifu: Mapped["UserData | None"] = relationship(
        "UserData",
        remote_side=[id],
        post_update=True,
    )

    @property
    def user_config(self) -> UserConfig:
        return UserConfig.from_dict(self.config)

    @user_config.setter
    def user_config(self, config: UserConfig) -> None:
        self.config = config.to_dict()

    def __repr__(self) -> str:
        return f"<UserData(id={self.id}, username='{self.username}', full_name='{self.full_name}')>"


class ChatData(Base):
    __tablename__ = "chat_data"

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=False,
        index=True,
    )

    title: Mapped[str] = mapped_column(String(256), nullable=False)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)

    config: Mapped[dict] = mapped_column(
        JSON,
        default=lambda: asdict(ChatConfig()),
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    members: Mapped[List["UserData"]] = relationship(
        "UserData",
        secondary="user_chat_association",
        back_populates="chats",
        primaryjoin="ChatData.id == UserChatAssociation.chat_id",
        secondaryjoin="UserData.id == UserChatAssociation.user_id",
        lazy="noload",
    )

    quotes: Mapped[List["Quote"]] = relationship(
        "Quote",
        back_populates="chat",
        cascade="all, delete-orphan",
        lazy="noload",
    )

    @property
    def chat_config(self) -> ChatConfig:
        return ChatConfig.from_dict(self.config)

    @chat_config.setter
    def chat_config(self, config: ChatConfig) -> None:
        self.config = config.to_dict()

    def __repr__(self) -> str:
        return f"<ChatData(id={self.id}, title='{self.title}', username='{self.username}')>"


class Quote(Base):
    __tablename__ = "quotes"

    link: Mapped[str] = mapped_column(String(256), primary_key=True)

    chat_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("chat_data.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("user_data.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    qer_id: Mapped[int] = mapped_column(
        BigInteger,
        index=True,
    )

    message_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    text: Mapped[str | None] = mapped_column(String(4096), nullable=True)
    img: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    user: Mapped["UserData"] = relationship(
        lambda: UserData,
        foreign_keys=lambda: [Quote.user_id],
        back_populates="quotes",
        lazy="noload",
    )
    chat: Mapped["ChatData"] = relationship(
        "ChatData",
        back_populates="quotes",
        lazy="noload",
    )

    def __repr__(self) -> str:
        return f"<Quote(link='{self.link}', chat_id={self.chat_id}, user_id={self.user_id})>"
