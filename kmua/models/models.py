from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    LargeBinary,
    String,
    func,
    JSON,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


class UserChatAssociation(Base):
    __tablename__ = "user_chat_association"
    user_id = Column(
        BigInteger, ForeignKey("user_data.id"), primary_key=True, autoincrement=False
    )
    chat_id = Column(
        BigInteger, ForeignKey("chat_data.id"), primary_key=True, autoincrement=False
    )
    waifu_id = Column(BigInteger, ForeignKey("user_data.id"), default=None)
    is_bot_admin = Column(Boolean, default=False)

    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class UserData(Base):
    __tablename__ = "user_data"
    id = Column(BigInteger, primary_key=True, index=True, autoincrement=False)
    username = Column(String(32))
    full_name = Column(String(128), nullable=False)
    avatar_small_blob = Column(LargeBinary(65536), default=None)
    avatar_big_blob = Column(LargeBinary(65536), default=None)
    avatar_big_id = Column(String(128), default=None)

    chats = relationship(
        "ChatData",
        secondary=UserChatAssociation.__tablename__,
        back_populates="members",
        primaryjoin="UserData.id==UserChatAssociation.user_id",
        secondaryjoin="ChatData.id==UserChatAssociation.chat_id",
    )

    quotes = relationship("Quote", back_populates="user")

    is_married = Column(Boolean, default=False)
    married_waifu_id = Column(BigInteger, default=None)
    waifu_mention = Column(Boolean, default=True)

    is_bot = Column(Boolean, default=False)
    is_real_user = Column(Boolean, default=True)  # 频道身份, bot, 匿名用户等 为 False
    is_bot_global_admin = Column(Boolean, default=False)

    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint(
            "is_married = 0 OR (is_married = 1 AND married_waifu_id IS NOT NULL)"
        ),
    )


class ChatData(Base):
    __tablename__ = "chat_data"
    id = Column(BigInteger, primary_key=True, index=True, autoincrement=False)
    waifu_disabled = Column(Boolean, default=False)
    delete_events_enabled = Column(Boolean, default=False)
    unpin_channel_pin_enabled = Column(Boolean, default=False)
    message_search_enabled = Column(Boolean, default=False)
    quote_probability = Column(Float, default=0.001)
    title = Column(String(128), nullable=False)
    members = relationship(
        "UserData",
        secondary=UserChatAssociation.__tablename__,
        back_populates="chats",
        primaryjoin="ChatData.id==UserChatAssociation.chat_id",
        secondaryjoin="UserData.id==UserChatAssociation.user_id",
    )
    greet = Column(String(4096), default=None)
    title_permissions = Column(JSON, default={})

    quotes = relationship("Quote", back_populates="chat")
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class Quote(Base):
    __tablename__ = "quotes"
    chat_id = Column(BigInteger, ForeignKey("chat_data.id"))
    message_id = Column(BigInteger, nullable=False)
    link = Column(String(128), nullable=False, primary_key=True)
    user_id = Column(BigInteger, ForeignKey("user_data.id"))
    qer_id = Column(BigInteger)  # 使用 q 的人
    text = Column(String(4096), nullable=True, default=None)
    img = Column(String(128), nullable=True, default=None, comment="图片的 file id")
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    user = relationship("UserData", back_populates="quotes")
    chat = relationship("ChatData", back_populates="quotes")
