from datetime import UTC, date, datetime, timedelta

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from kmua.database.agent_quota import (
    CREDIT_REASON_ADMIN,
    CREDIT_REASON_USAGE,
    SCOPE_CHAT,
    get_balance_spent,
)
from kmua.database.models import AgentCreditLedger


async def test_balance_spent_counts_only_usage_deductions_for_the_account_day() -> None:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.exec_driver_sql(
            """
            CREATE TABLE agent_credit_ledger (
                id INTEGER PRIMARY KEY,
                scope VARCHAR(16) NOT NULL,
                scope_id BIGINT NOT NULL,
                delta BIGINT NOT NULL,
                balance_after BIGINT NOT NULL,
                reason VARCHAR(32) NOT NULL,
                ref VARCHAR(128),
                created_at DATETIME NOT NULL
            )
            """
        )

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    day = date(2026, 11, 25)
    start = datetime(2026, 11, 25, tzinfo=UTC)
    async with session_factory() as session:
        session.add_all(
            [
                AgentCreditLedger(
                    scope=SCOPE_CHAT,
                    scope_id=1,
                    delta=-200,
                    balance_after=9_800,
                    reason=CREDIT_REASON_USAGE,
                    created_at=start,
                ),
                AgentCreditLedger(
                    scope=SCOPE_CHAT,
                    scope_id=1,
                    delta=-150,
                    balance_after=9_650,
                    reason=CREDIT_REASON_USAGE,
                    created_at=start + timedelta(hours=1),
                ),
                AgentCreditLedger(
                    scope=SCOPE_CHAT,
                    scope_id=1,
                    delta=500,
                    balance_after=10_150,
                    reason=CREDIT_REASON_ADMIN,
                    created_at=start + timedelta(hours=2),
                ),
                AgentCreditLedger(
                    scope=SCOPE_CHAT,
                    scope_id=1,
                    delta=-900,
                    balance_after=9_250,
                    reason=CREDIT_REASON_USAGE,
                    created_at=start - timedelta(seconds=1),
                ),
                AgentCreditLedger(
                    scope=SCOPE_CHAT,
                    scope_id=2,
                    delta=-50,
                    balance_after=9_950,
                    reason=CREDIT_REASON_USAGE,
                    created_at=start,
                ),
            ]
        )
        await session.commit()

        assert await get_balance_spent(SCOPE_CHAT, 1, day, session=session) == 350

    await engine.dispose()
