"""add_user_chat_blocked_flags

Revision ID: e1f2a3b4c5d6
Revises: b7c8d9e0f1a2
Create Date: 2026-08-11 10:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e1f2a3b4c5d6"
down_revision: str | None = "de6861319b84"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    insp = sa.inspect(bind)

    for table, column in (
        ("user_data", "is_blocked"),
        ("chat_data", "is_blocked"),
    ):
        if not insp.has_table(table):
            continue
        existing_cols = {c["name"] for c in insp.get_columns(table)}
        if column not in existing_cols:
            op.add_column(
                table,
                sa.Column(
                    column,
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.false(),
                ),
            )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("user_data", "is_blocked")
    op.drop_column("chat_data", "is_blocked")
