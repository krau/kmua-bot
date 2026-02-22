"""add_bottle_replies

Revision ID: f5e6g7h8i9j0
Revises: a1b2c3d4e5f6
Create Date: 2025-02-22 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f5e6g7h8i9j0"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    insp = sa.inspect(bind)

    table_name = "bottle_replies"
    if insp.has_table(table_name):
        return

    op.create_table(
        "bottle_replies",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("bottle_id", sa.BigInteger(), nullable=False),
        sa.Column("replier_id", sa.BigInteger(), nullable=True),
        sa.Column("text", sa.String(length=4096), nullable=False),
        sa.Column(
            "is_anonymous",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("file_id", sa.String(length=256), nullable=True),
        sa.Column("media_type", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["bottle_id"], ["bottles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["replier_id"], ["user_data.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_bottle_replies_id"), "bottle_replies", ["id"], unique=False
    )
    op.create_index(
        op.f("ix_bottle_replies_bottle_id"),
        "bottle_replies",
        ["bottle_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_bottle_replies_replier_id"),
        "bottle_replies",
        ["replier_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_bottle_replies_replier_id"), table_name="bottle_replies")
    op.drop_index(op.f("ix_bottle_replies_bottle_id"), table_name="bottle_replies")
    op.drop_index(op.f("ix_bottle_replies_id"), table_name="bottle_replies")
    op.drop_table("bottle_replies")
