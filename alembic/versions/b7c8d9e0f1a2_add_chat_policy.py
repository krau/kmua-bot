"""add_chat_policy

Revision ID: b7c8d9e0f1a2
Revises: f5e6g7h8i9j0
Create Date: 2026-07-28 12:00:00.000000

Operator-controlled per-chat settings, starting with the agent whitelist that used
to live in `settings.toml`. The flags themselves are in a JSON column, so the next
"which groups may do X" question is a field rather than another table and another
migration.

Existing `agent_whitelist` entries in the config file are seeded on first start by
the application, not here: this migration runs without application config loaded, and
a data migration reading settings would tie the schema history to whatever the config
happened to say at upgrade time.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b7c8d9e0f1a2"
down_revision: str | None = "f5e6g7h8i9j0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    insp = sa.inspect(bind)

    table_name = "chat_policy"
    if insp.has_table(table_name):
        return

    op.create_table(
        table_name,
        sa.Column("chat_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("chat_title", sa.String(length=256), nullable=True),
        sa.Column("policy", sa.JSON(), nullable=True),
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
        sa.Column("note", sa.String(length=256), nullable=True),
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
        sa.PrimaryKeyConstraint("chat_id"),
    )
    op.create_index(
        op.f("ix_chat_policy_chat_id"), table_name, ["chat_id"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_chat_policy_chat_id"), table_name="chat_policy")
    op.drop_table("chat_policy")
