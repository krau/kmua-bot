"""index_created_at_window_counts

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-10-11 00:00:00.000000

The panel dashboard counts rows created in the last week for five tables, and it
polls those counters while the page is open. Without an index on `created_at` every
one of those counts is a full table scan, which is what made the page slow on a
database with a real amount of history.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e5f6a7b8c9d0"
down_revision: str | None = "d4e5f6a7b8c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEXES = (
    ("ix_quotes_created_at", "quotes"),
    ("ix_user_chat_association_created_at", "user_chat_association"),
    ("ix_bottles_created_at", "bottles"),
    ("ix_bottle_replies_created_at", "bottle_replies"),
)


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    insp = sa.inspect(bind)
    for index_name, table_name in _INDEXES:
        if not insp.has_table(table_name):
            continue
        if index_name in {index["name"] for index in insp.get_indexes(table_name)}:
            continue
        op.create_index(index_name, table_name, ["created_at"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    insp = sa.inspect(bind)
    for index_name, table_name in _INDEXES:
        if not insp.has_table(table_name):
            continue
        if index_name in {index["name"] for index in insp.get_indexes(table_name)}:
            op.drop_index(index_name, table_name=table_name)
