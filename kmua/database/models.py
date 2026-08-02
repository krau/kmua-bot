from dataclasses import asdict, dataclass, field
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
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
    affection: int = 0
    coins: int = 144 * 16

    @classmethod
    def from_dict(cls, data: dict | None) -> "UserConfig":
        if data is None:
            return cls()
        return cls(
            lang=data.get("lang", "zh-CN"),
            coins=data.get("coins", 144 * 16),
            affection=data.get("affection", 0),
        )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ChatConfig:
    waifu_enabled: bool = True
    delete_events_enabled: bool = False
    unpin_channel_pin_enabled: bool = False
    quote_probability: float = 0.001
    quote_pin_message: bool = True
    title_permissions: dict | None = None
    greeting: str | None = None
    ai_reply: bool = True
    ai_reply_other_bots_enabled: bool = False
    ai_comment: bool = False
    setu_enabled: bool = True
    convert_b23_enabled: bool = True
    parse_artwork_enabled: bool = True
    parse_sites_enabled: dict[str, bool] = field(default_factory=dict)
    pick_bottle_enabled: bool = True
    group_memory_enabled: bool = True
    parse_wechat_enabled: bool = True
    rss_agent_summary: bool = False
    rss_agent_broadcast: bool = False
    lang: str = "zh-CN"

    @classmethod
    def from_dict(cls, data: dict | None) -> "ChatConfig":
        if data is None:
            return cls()
        return cls(
            waifu_enabled=data.get("waifu_enabled", True),
            delete_events_enabled=data.get("delete_events_enabled", False),
            unpin_channel_pin_enabled=data.get("unpin_channel_pin_enabled", False),
            quote_probability=data.get("quote_probability", 0.001),
            quote_pin_message=data.get("quote_pin_message", False),
            title_permissions=data.get("title_permissions", {}),
            greeting=data.get("greeting", None),
            ai_reply=data.get("ai_reply", True),
            ai_reply_other_bots_enabled=data.get("ai_reply_other_bots_enabled", False),
            setu_enabled=data.get("setu_enabled", True),
            convert_b23_enabled=data.get("convert_b23_enabled", False),
            parse_artwork_enabled=data.get("parse_artwork_enabled", True),
            parse_sites_enabled=data.get("parse_sites_enabled") or {},
            pick_bottle_enabled=data.get("pick_bottle_enabled", True),
            ai_comment=data.get("ai_comment", False),
            group_memory_enabled=data.get("group_memory_enabled", True),
            parse_wechat_enabled=data.get("parse_wechat_enabled", True),
            rss_agent_summary=data.get("rss_agent_summary", False),
            rss_agent_broadcast=data.get("rss_agent_broadcast", False),
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

    chats: Mapped[list["ChatData"]] = relationship(
        "ChatData",
        secondary="user_chat_association",
        back_populates="members",
        primaryjoin="UserData.id == UserChatAssociation.user_id",
        secondaryjoin="ChatData.id == UserChatAssociation.chat_id",
        lazy="noload",
    )

    quotes: Mapped[list["Quote"]] = relationship(
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

    members: Mapped[list["UserData"]] = relationship(
        "UserData",
        secondary="user_chat_association",
        back_populates="chats",
        primaryjoin="ChatData.id == UserChatAssociation.chat_id",
        secondaryjoin="UserData.id == UserChatAssociation.user_id",
        lazy="noload",
    )

    quotes: Mapped[list["Quote"]] = relationship(
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
        foreign_keys=[user_id],
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


class Bottle(Base):
    __tablename__ = "bottles"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
        index=True,
    )

    sender_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("user_data.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    text: Mapped[str] = mapped_column(String(4096), nullable=True)
    picks: Mapped[int] = mapped_column(BigInteger, default=0)
    reports: Mapped[int] = mapped_column(BigInteger, default=0)
    file_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    media_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    """
    meida_type can be one of the following:
    - image
    - video
    - audio
    - document
    - voice
    - None (for text-only bottles)
    """
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    last_picked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )

    def __repr__(self) -> str:
        return f"<Bottle(id={self.id}, sender_id={self.sender_id})>"


class BottleReply(Base):
    __tablename__ = "bottle_replies"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
        index=True,
    )
    bottle_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("bottles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    replier_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("user_data.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    text: Mapped[str] = mapped_column(String(4096), nullable=False)
    is_anonymous: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=sa.text("false")
    )
    file_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    media_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    def __repr__(self) -> str:
        return f"<BottleReply(id={self.id}, bottle_id={self.bottle_id}, replier_id={self.replier_id})>"


@dataclass
class ChatPolicy:
    """Per-chat settings the operator controls, as opposed to the group's admins.

    Deliberately separate from `ChatConfig`, which is what `/config` and the group
    settings page write: that document is saved wholesale by anyone who can manage
    the bot in the chat, so an operator-only field living there would be clobbered
    by the next group-admin save.

    Adding a field here needs no migration - the column is JSON and `from_dict`
    supplies the default for rows written before the field existed. That is the
    point of the shape: the next "which groups may do X" question is a field, not
    a table.
    """

    # Whether the AI agent may act here, when agent_whitelist_mode is on.
    agent_allowed: bool = False
    # Whether RSS subscriptions may be created here, when rss_whitelist_mode is on.
    rss_allowed: bool = False

    @classmethod
    def from_dict(cls, data: dict | None) -> "ChatPolicy":
        if data is None:
            return cls()
        return cls(
            agent_allowed=data.get("agent_allowed", False),
            rss_allowed=data.get("rss_allowed", False),
        )

    def to_dict(self) -> dict:
        return asdict(self)


class ChatPolicyData(Base):
    """Operator-controlled policy for one chat.

    A row exists only for chats an operator has actually made a decision about, so
    the table stays small and its absence is meaningful: no row means every policy
    is at its default.

    There is no FK to `chat_data`. An operator can grant a group access before the
    bot has ever seen a message in it, and a chat being purged from `chat_data`
    should not silently revoke a decision that was made deliberately. `chat_title`
    is a denormalised copy, kept only so the panel can label a row for a chat that
    is not in `chat_data` yet.
    """

    __tablename__ = "chat_policy"

    chat_id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=False,
        index=True,
    )
    # Nullable: a row added by id alone has no title until the bot sees the chat.
    chat_title: Mapped[str | None] = mapped_column(String(256), nullable=True)

    policy: Mapped[dict] = mapped_column(
        JSON,
        default=lambda: asdict(ChatPolicy()),
    )

    # Who last changed it, for the audit trail. Not an FK, as above.
    updated_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    note: Mapped[str | None] = mapped_column(String(256), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    @property
    def chat_policy(self) -> ChatPolicy:
        return ChatPolicy.from_dict(self.policy)

    @chat_policy.setter
    def chat_policy(self, policy: ChatPolicy) -> None:
        self.policy = policy.to_dict()

    def __repr__(self) -> str:
        return f"<ChatPolicyData(chat_id={self.chat_id}, policy={self.policy})>"


class Gift(Base):
    __tablename__ = "gifts"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
        index=True,
    )
    owner_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("user_data.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    rarity: Mapped[int] = mapped_column(Integer, nullable=False)
    sent_to_bot: Mapped[bool] = mapped_column(Boolean, default=False)

    gift_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    def __repr__(self) -> str:
        return (
            f"<Gift(id={self.id}, owner_id={self.owner_id}, gift_id='{self.gift_id}')>"
        )


class RssFeed(Base):
    """One remote feed, fetched once however many chats subscribe to it.

    Deduplicated by URL: polling the same feed once per subscriber would multiply
    outbound requests by the subscriber count for identical bytes.

    `seen_entry_ids` is the newest-N entry ids from the last successful fetch, and it
    is how "new" is decided. Timestamps are not usable for this: `published_parsed`
    is missing or wrong on a large share of real feeds, and a feed that republishes
    with a bumped date would re-push every entry. An id set has no such failure mode.
    """

    __tablename__ = "rss_feeds"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True, index=True
    )
    url: Mapped[str] = mapped_column(String(1024), nullable=False, unique=True)
    # Feed's self-reported title, shown in listings. None until the first fetch.
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # Conditional-GET state, replayed as request headers on the next poll.
    etag: Mapped[str | None] = mapped_column(String(256), nullable=True)
    last_modified: Mapped[str | None] = mapped_column(String(256), nullable=True)

    # Entry ids already delivered; see the class docstring.
    seen_entry_ids: Mapped[list] = mapped_column(JSON, default=list)

    last_fetched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    # Last failure text, cleared on success. Surfaced in /rss list and the panel so a
    # dead feed is visible instead of silently never pushing.
    last_error: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # Consecutive failures. At >= MAX_FAILURES the feed is skipped by the poll job.
    failure_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=sa.text("0")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    def __repr__(self) -> str:
        return f"<RssFeed(id={self.id}, url='{self.url}')>"


class RssSubscription(Base):
    """One chat's subscription to one feed.

    No FK to `chat_data`: like `chat_policy`, a subscription may be created for a chat
    before the bot has any row for it, and purging a chat should not silently drop a
    deliberate subscription. The push job resolves the chat id against Telegram anyway.
    """

    __tablename__ = "rss_subscriptions"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True, index=True
    )
    feed_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("rss_feeds.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    # Who created it, for the audit trail. Not an FK, as above.
    created_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    paused: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=sa.text("false")
    )
    # Per-subscription poll interval in minutes; None means "follow the global
    # rss_interval". The feed's effective interval is the minimum across its
    # unpaused subscriptions.
    interval_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    feed: Mapped[RssFeed] = relationship(lazy="joined")

    __table_args__ = (
        sa.UniqueConstraint("chat_id", "feed_id", name="uq_rss_subscription_chat_feed"),
    )

    def __repr__(self) -> str:
        return f"<RssSubscription(chat_id={self.chat_id}, feed_id={self.feed_id})>"
