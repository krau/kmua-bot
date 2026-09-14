"""index_agent_runs_session

Revision ID: d4e5f6a7b8c9
Revises: c3f1a7b9d2e4
Create Date: 2026-09-14 00:00:00.000000

`session_id` is read on every turn (to find out whether a conversation already has
records) and grouped on by the retention cleanup, which now deletes a conversation's
records together.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d4e5f6a7b8c9"
down_revision: str | None = "c3f1a7b9d2e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX = "ix_agent_runs_session_id"


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table("agent_runs"):
        return
    if _INDEX in {index["name"] for index in insp.get_indexes("agent_runs")}:
        return
    op.create_index(_INDEX, "agent_runs", ["session_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if _INDEX in {index["name"] for index in insp.get_indexes("agent_runs")}:
        op.drop_index(_INDEX, table_name="agent_runs")
