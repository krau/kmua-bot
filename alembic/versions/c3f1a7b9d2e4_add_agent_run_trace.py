"""add_agent_run_trace

Revision ID: c3f1a7b9d2e4
Revises: b1c2d3e4f5a6
Create Date: 2026-09-12 00:00:00.000000

One row per agent run and one per step of it: the request each turn actually sent,
the response it got back, every tool call and its result, and how the run ended.
Append-only, written once at run end, so a run that never finished leaves nothing
behind. `parent_run_id` links a nested run (compaction, transcription) to the turn
that spawned it; it is a plain column with no foreign key, like the quota tables.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c3f1a7b9d2e4"
down_revision: str | None = "b1c2d3e4f5a6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RUN_INDEXES: tuple[tuple[str, list[str]], ...] = (
    ("ix_agent_runs_started_at", ["started_at"]),
    ("ix_agent_runs_chat_started", ["chat_id", "started_at"]),
    ("ix_agent_runs_user_started", ["user_id", "started_at"]),
    ("ix_agent_runs_status_started", ["status", "started_at"]),
    ("ix_agent_runs_kind_started", ["kind", "started_at"]),
)


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not insp.has_table("agent_runs"):
        op.create_table(
            "agent_runs",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("kind", sa.String(length=32), nullable=False),
            sa.Column("status", sa.String(length=16), nullable=False),
            sa.Column("reject_reason", sa.String(length=16), nullable=True),
            sa.Column("chat_id", sa.BigInteger(), nullable=True),
            sa.Column("user_id", sa.BigInteger(), nullable=True),
            sa.Column("message_id", sa.BigInteger(), nullable=True),
            sa.Column("parent_run_id", sa.Integer(), nullable=True),
            sa.Column("model_name", sa.String(length=128), nullable=True),
            sa.Column("model_role", sa.String(length=16), nullable=True),
            sa.Column(
                "streaming",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column(
                "duration_ms", sa.Integer(), nullable=False, server_default=sa.text("0")
            ),
            sa.Column(
                "requests", sa.Integer(), nullable=False, server_default=sa.text("0")
            ),
            sa.Column(
                "tool_calls", sa.Integer(), nullable=False, server_default=sa.text("0")
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
                "cache_read_tokens",
                sa.BigInteger(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column(
                "cache_write_tokens",
                sa.BigInteger(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column("output_kind", sa.String(length=16), nullable=True),
            sa.Column("output_text", sa.Text(), nullable=True),
            sa.Column("output_chars", sa.Integer(), nullable=True),
            sa.Column("error_class", sa.String(length=128), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column(
                "event_count", sa.Integer(), nullable=False, server_default=sa.text("0")
            ),
            sa.Column(
                "events_dropped",
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
        )
        op.create_index(op.f("ix_agent_runs_id"), "agent_runs", ["id"], unique=False)
        for name, columns in _RUN_INDEXES:
            op.create_index(name, "agent_runs", columns, unique=False)

    if not insp.has_table("agent_run_events"):
        op.create_table(
            "agent_run_events",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("run_id", sa.Integer(), nullable=False),
            sa.Column("seq", sa.Integer(), nullable=False),
            sa.Column("kind", sa.String(length=24), nullable=False),
            sa.Column("name", sa.String(length=128), nullable=True),
            sa.Column(
                "status",
                sa.String(length=16),
                nullable=False,
                server_default=sa.text("'ok'"),
            ),
            sa.Column("duration_ms", sa.Integer(), nullable=True),
            sa.Column("payload", sa.JSON(), nullable=True),
            sa.Column("payload_chars", sa.Integer(), nullable=True),
            sa.Column(
                "truncated",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("(CURRENT_TIMESTAMP)"),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("run_id", "seq", name="uq_agent_run_events_run_seq"),
        )
        op.create_index(
            op.f("ix_agent_run_events_id"),
            "agent_run_events",
            ["id"],
            unique=False,
        )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_agent_run_events_id"), table_name="agent_run_events")
    op.drop_table("agent_run_events")
    for name, _columns in reversed(_RUN_INDEXES):
        op.drop_index(name, table_name="agent_runs")
    op.drop_index(op.f("ix_agent_runs_id"), table_name="agent_runs")
    op.drop_table("agent_runs")
