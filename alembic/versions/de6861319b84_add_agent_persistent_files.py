"""add_agent_persistent_files

Revision ID: de6861319b84
Revises: c1d2e3f4a5b6
Create Date: 2026-08-05 21:27:28.561003

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "de6861319b84"
down_revision: str | None = "c1d2e3f4a5b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    insp = sa.inspect(bind)

    table_name = "agent_persistent_files"
    if insp.has_table(table_name):
        return

    op.create_table(
        table_name,
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("description", sa.String(length=1024), nullable=True),
        sa.Column("tg_message_id", sa.BigInteger(), nullable=False),
        sa.Column("file_id", sa.String(length=512), nullable=False),
        sa.Column("file_unique_id", sa.String(length=512), nullable=False),
        sa.Column("file_name", sa.String(length=512), nullable=True),
        sa.Column("mime_type", sa.String(length=256), nullable=True),
        sa.Column("file_size", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("chat_id", "name", name="uq_agent_persistent_chat_name"),
    )
    op.create_index("ix_agent_persistent_files_id", table_name, ["id"], unique=False)
    op.create_index(
        "ix_agent_persistent_files_chat_id", table_name, ["chat_id"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("agent_persistent_files")
