from dataclasses import asdict, dataclass

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    LargeBinary,
    String,
    func,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


class UserChatAssociation(Base):
    __tablename__ = "user_chat_association"
    user_id = Column(
        BigInteger,
        ForeignKey("user_data.id"),
        primary_key=True,
        autoincrement=False,
        index=True,
    )
    chat_id = Column(
        BigInteger,
        ForeignKey("chat_data.id"),
        primary_key=True,
        autoincrement=False,
        index=True,
    )
    waifu_id = Column(BigInteger, ForeignKey("user_data.id"), default=None, index=True)
    is_bot_admin = Column(Boolean, default=False)

    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class UserData(Base):
    __tablename__ = "user_data"
    id = Column(BigInteger, primary_key=True, index=True, autoincrement=False)
    username = Column(String(64))
    full_name = Column(String(256), nullable=False)
    avatar_small_blob = Column(LargeBinary(65536), default=None)
    avatar_big_blob = Column(LargeBinary(65536), default=None)
    avatar_big_id = Column(String(256), default=None)

    is_married = Column(Boolean, default=False)
    married_waifu_id = Column(BigInteger, default=None, index=True)
    waifu_mention = Column(Boolean, default=True)

    is_bot = Column(Boolean, default=False)
    is_real_user = Column(Boolean, default=True)  # 频道身份, bot, 匿名用户等 为 False
    is_bot_global_admin = Column(Boolean, default=False)

    chats = relationship(
        "ChatData",
        secondary=UserChatAssociation.__tablename__,
        back_populates="members",
        primaryjoin="UserData.id==UserChatAssociation.user_id",
        secondaryjoin="ChatData.id==UserChatAssociation.chat_id",
    )

    quotes = relationship("Quote", back_populates="user")

    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint(
            "is_married = 0 OR (is_married = 1 AND married_waifu_id IS NOT NULL)"
        ),
    )

    def __str__(self):
        return f"""
id: {self.id}
username: {self.username}
full_name: {self.full_name}
头像缓存id(大尺寸): {True if self.avatar_big_id else None}
头像(大尺寸): {True if self.avatar_big_blob else None}
头像(小尺寸): {True if self.avatar_small_blob else None}
已结婚: {self.is_married}
已结婚的老婆id: {self.married_waifu_id}
是否允许被提及: {self.waifu_mention}
是否为bot: {self.is_bot}
是否为真实用户: {self.is_real_user}
是否为bot全局管理: {self.is_bot_global_admin}
created_at: {self.created_at.strftime("%Y-%m-%d %H:%M:%S")}
updated_at: {self.updated_at.strftime("%Y-%m-%d %H:%M:%S")}
"""


@dataclass
class ChatConfig:
    waifu_enabled: bool = True
    delete_events_enabled: bool = False
    unpin_channel_pin_enabled: bool = False
    message_search_enabled: bool = False
    quote_probability: float = 0.001
    quote_pin_message: bool = True
    title_permissions: dict = None
    greeting: str = None
    ai_reply: bool = True
    setu_enabled: bool = True
    convert_b23_enabled: bool = True

    @staticmethod
    def from_dict(data: dict):
        return ChatConfig(
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
        )

    def to_dict(self):
        return asdict(self)


class ChatData(Base):
    __tablename__ = "chat_data"
    id = Column(BigInteger, primary_key=True, index=True, autoincrement=False)
    title = Column(String(256), nullable=False)
    username = Column(String(64), nullable=True)
    members = relationship(
        "UserData",
        secondary=UserChatAssociation.__tablename__,
        back_populates="chats",
        primaryjoin="ChatData.id==UserChatAssociation.chat_id",
        secondaryjoin="UserData.id==UserChatAssociation.user_id",
    )
    config = Column(JSON, default=asdict(ChatConfig()))

    quotes = relationship("Quote", back_populates="chat")
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class Quote(Base):
    __tablename__ = "quotes"
    chat_id = Column(BigInteger, ForeignKey("chat_data.id"), index=True)
    message_id = Column(BigInteger, nullable=False, index=True)
    link = Column(String(256), nullable=False, primary_key=True)
    user_id = Column(BigInteger, ForeignKey("user_data.id"), index=True)
    qer_id = Column(BigInteger, index=True)  # 使用 q 的人
    text = Column(String(4096), nullable=True, default=None)
    img = Column(String(256), nullable=True, default=None, comment="图片的 file id")
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    user = relationship("UserData", back_populates="quotes")
    chat = relationship("ChatData", back_populates="quotes")
