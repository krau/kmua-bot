from sqlalchemy import (
    Column,
    func,
    Integer,
    String,
    Float,
    BLOB,
    Boolean,
    DateTime,
    ForeignKey,
    Table,
)
from sqlalchemy.orm import relationship
from sqlalchemy import CheckConstraint
from .db import Base


class UserChatAssociation(Base):
    __tablename__ = "user_chat_association"
    user_id = Column(Integer, ForeignKey("user_data.id"), primary_key=True)
    chat_id = Column(Integer, ForeignKey("chat_data.id"), primary_key=True)
    waifu_id = Column(Integer, ForeignKey("user_data.id"), default=None)

    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class UserData(Base):
    __tablename__ = "user_data"
    id = Column(Integer, primary_key=True)
    username = Column(String)
    full_name = Column(String, nullable=False)
    avatar_small_blob = Column(BLOB, default=None)
    avatar_big_blob = Column(BLOB, default=None)
    avatar_big_id = Column(String, default=None)

    chats = relationship(
        "ChatData",
        secondary=UserChatAssociation.__tablename__,
        back_populates="members",
        primaryjoin="UserData.id==UserChatAssociation.user_id",
        secondaryjoin="ChatData.id==UserChatAssociation.chat_id",
    )

    quotes = relationship("Quote", back_populates="user")

    is_married = Column(Boolean, default=False)
    married_waifu_id = Column(Integer, default=None)
    waifu_mention = Column(Boolean, default=True)

    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint(
            "is_married = 0 OR (is_married = 1 AND married_waifu_id IS NOT NULL)"
        ),
    )


class ChatData(Base):
    __tablename__ = "chat_data"
    id = Column(Integer, primary_key=True)
    quote_probability = Column(Float, default=0.001)
    members = relationship(
        "UserData",
        secondary=UserChatAssociation.__tablename__,
        back_populates="chats",
        primaryjoin="ChatData.id==UserChatAssociation.chat_id",
        secondaryjoin="UserData.id==UserChatAssociation.user_id",
    )

    quotes = relationship("Quote", back_populates="chat")


class Quote(Base):
    __tablename__ = "quotes"
    quote_id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(Integer, ForeignKey("chat_data.id"))
    user_id = Column(Integer, ForeignKey("user_data.id"))
    message_id = Column(Integer, nullable=False)
    text = Column(String, nullable=True, default=None)
    img = Column(String, nullable=True, default=None, comment="图片的 file id")
    is_deleted = Column(Boolean, default=False)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    user = relationship("UserData", back_populates="quotes")
    chat = relationship("ChatData", back_populates="quotes")
