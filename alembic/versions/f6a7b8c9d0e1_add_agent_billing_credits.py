"""add_agent_billing_credits

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-11-22 00:00:00.000000

Agent quota moves from raw model tokens to billing credits while the raw token
counters stay intact. One credit is 1,000 billable token units, rounded away from
zero. Existing usage, balances and ledger entries are compacted to that scale.
"""

from collections.abc import Callable, Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f6a7b8c9d0e1"
down_revision: str | None = "e5f6a7b8c9d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TOKENS_PER_CREDIT = 1_000
_USAGE_TABLE = "agent_usage_daily"


def _to_credits(value: int) -> int:
    """Round a token-unit value away from zero, preserving its sign."""
    if value == 0:
        return 0
    magnitude = (abs(value) + _TOKENS_PER_CREDIT - 1) // _TOKENS_PER_CREDIT
    return -magnitude if value < 0 else magnitude


def _to_token_units(value: int) -> int:
    return value * _TOKENS_PER_CREDIT


def _rewrite(
    table_name: str,
    columns: tuple[str, ...],
    convert: Callable[[int], int],
) -> None:
    """Rewrite selected integer columns of a small accounting table."""
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table(table_name):
        return

    table = sa.Table(table_name, sa.MetaData(), autoload_with=bind)
    present = tuple(column for column in columns if column in table.c)
    if not present:
        return
    primary_key = insp.get_pk_constraint(table_name).get("constrained_columns") or []
    if not primary_key:
        return

    rows = bind.execute(sa.select(table)).mappings().all()
    for row in rows:
        values = {column: convert(int(row[column] or 0)) for column in present}
        if all(values[column] == int(row[column] or 0) for column in present):
            continue
        where = sa.and_(*(table.c[column] == row[column] for column in primary_key))
        bind.execute(sa.update(table).where(where).values(**values))


def _rewrite_ledger(convert: Callable[[int], int]) -> None:
    """Rebuild ledger deltas from converted running balances.

    Rounding ``delta`` and ``balance_after`` independently makes the sum of ledger
    deltas disagree with the converted account balance. Instead, convert each
    historical balance, derive the delta from the previous converted balance, and
    pin the final row to the account's converted balance.
    """
    table_name = "agent_credit_ledger"
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table(table_name):
        return

    ledger = sa.Table(table_name, sa.MetaData(), autoload_with=bind)
    required = {"id", "scope", "scope_id", "delta", "balance_after"}
    if not required.issubset(ledger.c.keys()):
        return

    balances: dict[tuple[str, int], int] = {}
    if insp.has_table("agent_credits"):
        credits = sa.Table("agent_credits", sa.MetaData(), autoload_with=bind)
        if {"scope", "scope_id", "balance"}.issubset(credits.c.keys()):
            balances = {
                (row.scope, int(row.scope_id)): int(row.balance or 0)
                for row in bind.execute(
                    sa.select(credits.c.scope, credits.c.scope_id, credits.c.balance)
                )
            }

    rows_by_account: dict[tuple[str, int], list[sa.RowMapping]] = {}
    for row in bind.execute(
        sa.select(ledger).order_by(ledger.c.scope, ledger.c.scope_id, ledger.c.id)
    ).mappings():
        rows_by_account.setdefault((row["scope"], int(row["scope_id"])), []).append(row)

    for account, rows in rows_by_account.items():
        previous = 0
        final_balance = balances.get(account)
        for index, row in enumerate(rows):
            balance_after = convert(int(row["balance_after"] or 0))
            if index == len(rows) - 1 and final_balance is not None:
                balance_after = final_balance
            delta = balance_after - previous
            bind.execute(
                sa.update(ledger)
                .where(ledger.c.id == row["id"])
                .values(delta=delta, balance_after=balance_after)
            )
            previous = balance_after


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if insp.has_table(_USAGE_TABLE):
        columns = {column["name"] for column in insp.get_columns(_USAGE_TABLE)}
        if "free_used_tokens" in columns and "free_used_credits" not in columns:
            op.alter_column(
                _USAGE_TABLE,
                "free_used_tokens",
                new_column_name="free_used_credits",
                existing_type=sa.BigInteger(),
                existing_nullable=False,
                existing_server_default=sa.text("0"),
            )

        columns = {column["name"] for column in insp.get_columns(_USAGE_TABLE)}
        billed_added = "billed_credits" not in columns
        if billed_added:
            op.add_column(
                _USAGE_TABLE,
                sa.Column(
                    "billed_credits",
                    sa.BigInteger(),
                    nullable=False,
                    server_default=sa.text("0"),
                ),
            )
        if "cache_read_tokens" not in columns:
            op.add_column(
                _USAGE_TABLE,
                sa.Column(
                    "cache_read_tokens",
                    sa.BigInteger(),
                    nullable=False,
                    server_default=sa.text("0"),
                ),
            )
        if "cache_write_tokens" not in columns:
            op.add_column(
                _USAGE_TABLE,
                sa.Column(
                    "cache_write_tokens",
                    sa.BigInteger(),
                    nullable=False,
                    server_default=sa.text("0"),
                ),
            )
        if billed_added:
            # Historical free usage is the only recorded quota portion. Paid usage
            # lives in the credit ledger, so this backfill is conservative.
            op.execute(
                sa.text(
                    f"UPDATE {_USAGE_TABLE} "
                    "SET billed_credits = free_used_credits "
                    "WHERE billed_credits = 0"
                )
            )

    _rewrite(
        _USAGE_TABLE,
        ("free_used_credits", "billed_credits"),
        _to_credits,
    )
    _rewrite("agent_credits", ("balance",), _to_credits)
    _rewrite_ledger(_to_credits)


def downgrade() -> None:
    """Downgrade schema."""
    _rewrite(
        _USAGE_TABLE,
        ("free_used_credits", "billed_credits"),
        _to_token_units,
    )
    _rewrite("agent_credits", ("balance",), _to_token_units)
    _rewrite_ledger(_to_token_units)

    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table(_USAGE_TABLE):
        return

    columns = {column["name"] for column in insp.get_columns(_USAGE_TABLE)}
    if "cache_write_tokens" in columns:
        op.drop_column(_USAGE_TABLE, "cache_write_tokens")
    if "cache_read_tokens" in columns:
        op.drop_column(_USAGE_TABLE, "cache_read_tokens")
    if "billed_credits" in columns:
        op.drop_column(_USAGE_TABLE, "billed_credits")
    if "free_used_credits" in columns and "free_used_tokens" not in columns:
        op.alter_column(
            _USAGE_TABLE,
            "free_used_credits",
            new_column_name="free_used_tokens",
            existing_type=sa.BigInteger(),
            existing_nullable=False,
            existing_server_default=sa.text("0"),
        )
