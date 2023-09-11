from sqlalchemy import (
    Column,
    func,
    Integer,
    String,
    Float,
    BLOB,
    DateTime,
    ForeignKey,
    Table,
)
from sqlalchemy.orm import relationship
from .db import Base

_chat_members_association = Table(
    "chat_members",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("user_data.user_id")),
    Column("chat_id", Integer, ForeignKey("chat_data.chat_id")),
)


class UserData(Base):
    __tablename__ = "user_data"
    user_id = Column(Integer, primary_key=True)
    username = Column(String, nullable=False)
    full_name = Column(String, nullable=False)
    avatar_small_blob = Column(BLOB, default=None)
    avatar_big_blob = Column(BLOB, default=None)
    avatar_big_id = Column(String, default=None)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    chats = relationship(
        "ChatData", secondary=_chat_members_association, back_populates="members"
    )
    quotes = relationship("Quote", back_populates="user")


class ChatData(Base):
    __tablename__ = "chat_data"
    chat_id = Column(Integer, primary_key=True)
    quote_probability = Column(Float, default=0.001)
    members = relationship(
        "UserData", secondary=_chat_members_association, back_populates="chats"
    )
    quotes = relationship("Quote", back_populates="chat")


class Quote(Base):
    __tablename__ = "quotes"
    quote_id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(Integer, ForeignKey("chat_data.chat_id"))
    user_id = Column(Integer, ForeignKey("user_data.user_id"))
    message_id = Column(Integer, nullable=False)
    text = Column(String, nullable=True, default=None)
    img = Column(String, nullable=True, default=None, comment="图片的 file id")
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    user = relationship("UserData", back_populates="quotes")
    chat = relationship("ChatData", back_populates="quotes")
