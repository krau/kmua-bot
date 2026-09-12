"""add_agent_quota

Revision ID: b1c2d3e4f5a6
Revises: f3a4b5c6d7e8
Create Date: 2026-08-20 00:00:00.000000

Per-account agent quota, metered in tokens: daily counters, credit balances and the
append-only ledger that records every balance change. Accounts are `(scope, scope_id)`
pairs, where "user" is the speaker and "chat" is the conversation.

`agent_credits.balance` carries no non-negative constraint: a run's token usage is only
known once it finishes, so an overshoot is booked as a negative balance rather than
rejected.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b1c2d3e4f5a6"
down_revision: str | None = "f3a4b5c6d7e8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not insp.has_table("agent_usage_daily"):
        op.create_table(
            "agent_usage_daily",
            sa.Column("scope", sa.String(length=16), nullable=False),
            sa.Column("scope_id", sa.BigInteger(), autoincrement=False, nullable=False),
            sa.Column("day", sa.Date(), nullable=False),
            sa.Column(
                "requests", sa.Integer(), nullable=False, server_default=sa.text("0")
            ),
            sa.Column(
                "free_used_tokens",
                sa.BigInteger(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column(
                "input_tokens",
                sa.BigInteger(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column(
                "output_tokens",
                sa.BigInteger(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("(CURRENT_TIMESTAMP)"),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("scope", "scope_id", "day"),
        )
        op.create_index(
            "ix_agent_usage_daily_day", "agent_usage_daily", ["day"], unique=False
        )

    if not insp.has_table("agent_credits"):
        op.create_table(
            "agent_credits",
            sa.Column("scope", sa.String(length=16), nullable=False),
            sa.Column("scope_id", sa.BigInteger(), autoincrement=False, nullable=False),
            sa.Column(
                "balance", sa.BigInteger(), nullable=False, server_default=sa.text("0")
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("(CURRENT_TIMESTAMP)"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("(CURRENT_TIMESTAMP)"),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("scope", "scope_id"),
        )

    if not insp.has_table("agent_credit_ledger"):
        op.create_table(
            "agent_credit_ledger",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("scope", sa.String(length=16), nullable=False),
            sa.Column("scope_id", sa.BigInteger(), nullable=False),
            sa.Column("delta", sa.BigInteger(), nullable=False),
            sa.Column("balance_after", sa.BigInteger(), nullable=False),
            sa.Column("reason", sa.String(length=32), nullable=False),
            sa.Column("ref", sa.String(length=128), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("(CURRENT_TIMESTAMP)"),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "scope", "scope_id", "ref", name="uq_agent_credit_ledger_scope_ref"
            ),
        )
        op.create_index(
            op.f("ix_agent_credit_ledger_id"),
            "agent_credit_ledger",
            ["id"],
            unique=False,
        )
        op.create_index(
            "ix_agent_credit_ledger_account",
            "agent_credit_ledger",
            ["scope", "scope_id"],
            unique=False,
        )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_agent_credit_ledger_account", table_name="agent_credit_ledger")
    op.drop_index(op.f("ix_agent_credit_ledger_id"), table_name="agent_credit_ledger")
    op.drop_table("agent_credit_ledger")
    op.drop_table("agent_credits")
    op.drop_index("ix_agent_usage_daily_day", table_name="agent_usage_daily")
    op.drop_table("agent_usage_daily")
