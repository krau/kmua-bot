"""add verification tables

Revision ID: f3a4b5c6d7e8
Revises: e1f2a3b4c5d6
Create Date: 2026-08-15 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f3a4b5c6d7e8"
down_revision: str | None = "e1f2a3b4c5d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if insp.has_table("verification_sessions"):
        index_names = {
            index["name"] for index in insp.get_indexes("verification_sessions")
        }
        if "uq_verification_sessions_chat_user" not in index_names:
            op.create_index(
                "uq_verification_sessions_chat_user",
                "verification_sessions",
                ["chat_id", "user_id"],
                unique=True,
            )

    if not insp.has_table("verification_sessions"):
        op.create_table(
            "verification_sessions",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("chat_id", sa.BigInteger(), nullable=False),
            sa.Column("user_id", sa.BigInteger(), nullable=False),
            sa.Column("method", sa.String(length=32), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("challenge_message_id", sa.BigInteger(), nullable=True),
            sa.Column("attempts_left", sa.Integer(), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("(CURRENT_TIMESTAMP)"),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            op.f("ix_verification_sessions_id"),
            "verification_sessions",
            ["id"],
            unique=False,
        )
        op.create_index(
            op.f("ix_verification_sessions_chat_id"),
            "verification_sessions",
            ["chat_id"],
            unique=False,
        )
        op.create_index(
            op.f("ix_verification_sessions_user_id"),
            "verification_sessions",
            ["user_id"],
            unique=False,
        )
        op.create_index(
            "uq_verification_sessions_chat_user",
            "verification_sessions",
            ["chat_id", "user_id"],
            unique=True,
        )

    if not insp.has_table("verification_members"):
        op.create_table(
            "verification_members",
            sa.Column("chat_id", sa.BigInteger(), nullable=False),
            sa.Column("user_id", sa.BigInteger(), nullable=False),
            sa.Column(
                "verified_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("(CURRENT_TIMESTAMP)"),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("chat_id", "user_id"),
        )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "uq_verification_sessions_chat_user", table_name="verification_sessions"
    )
    op.drop_index(
        op.f("ix_verification_sessions_user_id"), table_name="verification_sessions"
    )
    op.drop_index(
        op.f("ix_verification_sessions_chat_id"), table_name="verification_sessions"
    )
    op.drop_index(
        op.f("ix_verification_sessions_id"), table_name="verification_sessions"
    )
    op.drop_table("verification_sessions")
    op.drop_table("verification_members")
