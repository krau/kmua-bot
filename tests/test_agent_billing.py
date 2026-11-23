import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from pydantic_ai.usage import RunUsage

from kmua.plugins.agent import billing, quota, rss_digest


def test_cache_hits_in_usage_details_receive_cache_discount() -> None:
    usage = RunUsage(
        input_tokens=10_000,
        details={"prompt_cache_hit_tokens": 9_000},
    )

    meter = billing.from_run_usage(usage, cache_read_billing_percent=10)

    assert meter.cache_read_tokens == 9_000
    assert meter.credits == 2


async def test_shared_rss_settlement_keeps_the_metered_credit_total(
    monkeypatch,
) -> None:
    settled: list[tuple[int | None, billing.BillingUsage]] = []

    async def capture(subject: quota.Subject, meter: billing.BillingUsage) -> None:
        settled.append((subject.chat_id, meter))

    monkeypatch.setattr(quota, "settle_metered", capture)

    await rss_digest._settle_shared([-1001, -1002], RunUsage(input_tokens=1_000))

    assert [subject_chat for subject_chat, _ in settled] == [-1001, -1002]
    assert sum(meter.input_tokens for _, meter in settled) == 1_000
    assert sum(meter.credits for _, meter in settled) == 1


def test_migration_reconciles_ledger_deltas_in_both_directions() -> None:
    path = (
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "f6a7b8c9d0e1_add_agent_billing_credits.py"
    )
    spec = importlib.util.spec_from_file_location("agent_billing_migration", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    credits = sa.Table(
        "agent_credits",
        metadata,
        sa.Column("scope", sa.String, primary_key=True),
        sa.Column("scope_id", sa.Integer, primary_key=True),
        sa.Column("balance", sa.Integer, nullable=False),
    )
    ledger = sa.Table(
        "agent_credit_ledger",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("scope", sa.String, nullable=False),
        sa.Column("scope_id", sa.Integer, nullable=False),
        sa.Column("delta", sa.Integer, nullable=False),
        sa.Column("balance_after", sa.Integer, nullable=False),
    )
    metadata.create_all(engine)

    with engine.begin() as connection:
        connection.execute(credits.insert().values(scope="user", scope_id=1, balance=1))
        connection.execute(
            ledger.insert(),
            [
                {
                    "id": 1,
                    "scope": "user",
                    "scope_id": 1,
                    "delta": 500,
                    "balance_after": 500,
                },
                {
                    "id": 2,
                    "scope": "user",
                    "scope_id": 1,
                    "delta": 500,
                    "balance_after": 1_000,
                },
            ],
        )
        with Operations.context(MigrationContext.configure(connection)):
            migration._rewrite_ledger(migration._to_credits)

        rows = connection.execute(
            sa.select(ledger.c.delta, ledger.c.balance_after).order_by(ledger.c.id)
        ).all()

    assert rows == [(1, 1), (0, 1)]
    assert sum(row.delta for row in rows) == 1

    with engine.begin() as connection:
        connection.execute(
            credits.update()
            .where(credits.c.scope == "user", credits.c.scope_id == 1)
            .values(balance=1_000)
        )
        connection.execute(
            ledger.update().where(ledger.c.id == 1).values(delta=1, balance_after=1)
        )
        connection.execute(
            ledger.update().where(ledger.c.id == 2).values(delta=1, balance_after=1)
        )
        with Operations.context(MigrationContext.configure(connection)):
            migration._rewrite_ledger(migration._to_token_units)

        rows = connection.execute(
            sa.select(ledger.c.delta, ledger.c.balance_after).order_by(ledger.c.id)
        ).all()

    assert rows == [(1_000, 1_000), (0, 1_000)]
    assert sum(row.delta for row in rows) == 1_000
