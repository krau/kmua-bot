"""add_rss_subscriptions

Revision ID: c1d2e3f4a5b6
Revises: b7c8d9e0f1a2
Create Date: 2026-07-31 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c1d2e3f4a5b6"
down_revision: str | None = "b7c8d9e0f1a2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not insp.has_table("rss_feeds"):
        op.create_table(
            "rss_feeds",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("url", sa.String(length=1024), nullable=False),
            sa.Column("title", sa.String(length=512), nullable=True),
            sa.Column("etag", sa.String(length=256), nullable=True),
            sa.Column("last_modified", sa.String(length=256), nullable=True),
            sa.Column("seen_entry_ids", sa.JSON(), nullable=True),
            sa.Column("last_fetched_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_error", sa.String(length=512), nullable=True),
            sa.Column(
                "failure_count",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("(CURRENT_TIMESTAMP)"),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("url", name="uq_rss_feeds_url"),
        )
        op.create_index(op.f("ix_rss_feeds_id"), "rss_feeds", ["id"], unique=False)

    if not insp.has_table("rss_subscriptions"):
        op.create_table(
            "rss_subscriptions",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("feed_id", sa.Integer(), nullable=False),
            sa.Column("chat_id", sa.BigInteger(), nullable=False),
            sa.Column("created_by", sa.BigInteger(), nullable=True),
            sa.Column(
                "paused", sa.Boolean(), nullable=False, server_default=sa.text("false")
            ),
            sa.Column("interval_minutes", sa.Integer(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("(CURRENT_TIMESTAMP)"),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["feed_id"], ["rss_feeds.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "chat_id", "feed_id", name="uq_rss_subscription_chat_feed"
            ),
        )
        op.create_index(
            op.f("ix_rss_subscriptions_id"), "rss_subscriptions", ["id"], unique=False
        )
        op.create_index(
            op.f("ix_rss_subscriptions_feed_id"),
            "rss_subscriptions",
            ["feed_id"],
            unique=False,
        )
        op.create_index(
            op.f("ix_rss_subscriptions_chat_id"),
            "rss_subscriptions",
            ["chat_id"],
            unique=False,
        )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_rss_subscriptions_chat_id"), table_name="rss_subscriptions")
    op.drop_index(op.f("ix_rss_subscriptions_feed_id"), table_name="rss_subscriptions")
    op.drop_index(op.f("ix_rss_subscriptions_id"), table_name="rss_subscriptions")
    op.drop_table("rss_subscriptions")
    op.drop_index(op.f("ix_rss_feeds_id"), table_name="rss_feeds")
    op.drop_table("rss_feeds")
