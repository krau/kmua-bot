"""Agent 额度: 账户字典、每日用量、余额与余额流水, 单位一律是 token (输入 + 输出)。

两条独立闸门, 各自原子读写, 都不做读后写:
- 免费日额度: `agent_usage_daily.free_used_tokens` 与上限比较, 只扣到上限为止。
- 余额: `agent_credits.balance`, 扣减没有下限 —— 单次 run 的用量只有跑完才知道,
  用超的部分如实记成负余额(欠费), 由下一次调用的预检拦住。

账户用 `(scope, scope_id)` 表示: `SCOPE_USER` 是发言者, `SCOPE_CHAT` 是会话/群。
行都是按需创建的: 用量行在第一次扣费时建, 余额行在第一次发放或扣费时建。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import NamedTuple

import sqlalchemy
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .db import with_session, with_tx
from .models import AgentCredit, AgentCreditLedger, AgentUsageDaily

SCOPE_USER = "user"
SCOPE_CHAT = "chat"

CREDIT_REASON_ADMIN = "admin"
CREDIT_REASON_USAGE = "usage"

Account = tuple[str, int]


class ChargeAccount(NamedTuple):
    """一位付款方: 账户, 加上它的免费额度上限(token); None = 免费部分不限额。"""

    scope: str
    scope_id: int
    free_limit: int | None


def utc_day() -> date:
    """额度统计用的"今天": 固定 UTC, 与部署时区无关。"""
    return datetime.now(UTC).date()


async def _ensure_usage_row(
    session: AsyncSession, scope: str, scope_id: int, day: date
) -> None:
    """保证用量行存在, 让后面的读改有行可改。

    已存在是常态, 先查一次直接返回。不存在时插入, 并用 SAVEPOINT 兜住并发插入:
    Postgres 上一次唯一约束冲突会作废整个事务, 靠外层 except 是救不回来的。
    """
    existing = await session.get(
        AgentUsageDaily, {"scope": scope, "scope_id": scope_id, "day": day}
    )
    if existing is not None:
        return
    try:
        async with session.begin_nested():
            session.add(AgentUsageDaily(scope=scope, scope_id=scope_id, day=day))
    except IntegrityError:
        pass


async def _ensure_credit_row(session: AsyncSession, scope: str, scope_id: int) -> None:
    """同上, 针对余额行。"""
    existing = await session.get(AgentCredit, {"scope": scope, "scope_id": scope_id})
    if existing is not None:
        return
    try:
        async with session.begin_nested():
            session.add(AgentCredit(scope=scope, scope_id=scope_id, balance=0))
    except IntegrityError:
        pass


@with_session
async def get_usage(
    scope: str, scope_id: int, day: date, session: AsyncSession | None = None
) -> tuple[int, int, int, int]:
    """(requests, free_used_tokens, input_tokens, output_tokens); 没有行时全为 0。"""
    assert session is not None
    row = await session.get(
        AgentUsageDaily, {"scope": scope, "scope_id": scope_id, "day": day}
    )
    if row is None:
        return 0, 0, 0, 0
    return row.requests, row.free_used_tokens, row.input_tokens, row.output_tokens


@with_tx
async def spend_free(
    scope: str,
    scope_id: int,
    day: date,
    limit: int,
    tokens: int,
    session: AsyncSession | None = None,
) -> int:
    """从免费额度扣 tokens, 返回实际扣掉的量(0 表示该账户的免费额度已用尽)。

    上限与自增在同一条 UPDATE 里判断, 所以并发的两次扣减不会各自读到旧值再一起写:
    写入时若该行已经涨到放不下这次扣减, 整条语句不生效, 返回 0 —— 少扣的那部分会由
    调用方转给下一个账户, 因此只会"少占一点免费额度", 不会过冲上限, 也不会漏记用量。
    """
    assert session is not None
    if tokens <= 0 or limit <= 0:
        return 0
    await _ensure_usage_row(session, scope, scope_id, day)
    current = await session.scalar(
        sqlalchemy.select(AgentUsageDaily.free_used_tokens).where(
            AgentUsageDaily.scope == scope,
            AgentUsageDaily.scope_id == scope_id,
            AgentUsageDaily.day == day,
        )
    )
    take = min(tokens, max(0, limit - (current or 0)))
    if take <= 0:
        return 0
    result = await session.execute(
        sqlalchemy.update(AgentUsageDaily)
        .where(
            AgentUsageDaily.scope == scope,
            AgentUsageDaily.scope_id == scope_id,
            AgentUsageDaily.day == day,
            AgentUsageDaily.free_used_tokens + take <= limit,
        )
        .values(free_used_tokens=AgentUsageDaily.free_used_tokens + take)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:  # type: ignore[attr-defined]
        return 0
    return take


# 非末位付款方的扣减用"读到的值"做比较交换, 冲突就重试; 重试这么多次还抢不到, 说明这个
# 账户正被并发划扣, 余量交给下一位付款方即可 —— 少扣一次总好过记错一笔。
_CREDIT_CAS_RETRIES = 5


@with_tx
async def spend_credit(
    scope: str,
    scope_id: int,
    tokens: int,
    *,
    allow_debt: bool = False,
    session: AsyncSession | None = None,
) -> int:
    """从余额扣 tokens 并记流水, 返回**实际扣掉的量**。

    `allow_debt=False`(默认): 最多扣可用余额, 一分不超。判断"够不够"和扣减是两条语句,
    用"读到的余额"做比较交换 —— 并发的另一次扣减会让这次失败并重读, 而不是各自拿旧值叠加,
    所以发言者的个人余额既不会被绕过(顺序仍是个人的先付), 也不会被扣成欠费。

    `allow_debt=True`: 无条件扣减, 余额可以为负。只有末位付款方用它: 一次 run 花掉多少是
    跑完才知道的, 与其拒绝记账, 不如把欠费如实记下, 由下一次预检拦住。
    """
    assert session is not None
    if tokens <= 0:
        return 0
    await _ensure_credit_row(session, scope, scope_id)
    if allow_debt:
        balance = await session.scalar(
            sqlalchemy.update(AgentCredit)
            .where(AgentCredit.scope == scope, AgentCredit.scope_id == scope_id)
            .values(balance=AgentCredit.balance - tokens)
            .returning(AgentCredit.balance)
            .execution_options(synchronize_session=False)
        )
        assert balance is not None
        session.add(
            AgentCreditLedger(
                scope=scope,
                scope_id=scope_id,
                delta=-tokens,
                balance_after=balance,
                reason=CREDIT_REASON_USAGE,
            )
        )
        return tokens
    for _ in range(_CREDIT_CAS_RETRIES):
        observed = await session.scalar(
            sqlalchemy.select(AgentCredit.balance).where(
                AgentCredit.scope == scope, AgentCredit.scope_id == scope_id
            )
        )
        if observed is None or observed <= 0:
            return 0
        take = min(tokens, observed)
        result = await session.execute(
            sqlalchemy.update(AgentCredit)
            .where(
                AgentCredit.scope == scope,
                AgentCredit.scope_id == scope_id,
                AgentCredit.balance == observed,
            )
            .values(balance=observed - take)
            .execution_options(synchronize_session=False)
        )
        if result.rowcount == 1:  # type: ignore[attr-defined]
            session.add(
                AgentCreditLedger(
                    scope=scope,
                    scope_id=scope_id,
                    delta=-take,
                    balance_after=observed - take,
                    reason=CREDIT_REASON_USAGE,
                )
            )
            return take
    return 0


@with_tx
async def record_usage(
    accounts: Sequence[Account],
    day: date,
    input_tokens: int,
    output_tokens: int,
    session: AsyncSession | None = None,
) -> None:
    """记一次 run 的调用次数与 token: 加到本次调用涉及的每个账户上。"""
    assert session is not None
    for scope, scope_id in accounts:
        await _ensure_usage_row(session, scope, scope_id, day)
        await session.execute(
            sqlalchemy.update(AgentUsageDaily)
            .where(
                AgentUsageDaily.scope == scope,
                AgentUsageDaily.scope_id == scope_id,
                AgentUsageDaily.day == day,
            )
            .values(
                requests=AgentUsageDaily.requests + 1,
                input_tokens=AgentUsageDaily.input_tokens + input_tokens,
                output_tokens=AgentUsageDaily.output_tokens + output_tokens,
            )
            .execution_options(synchronize_session=False)
        )


@with_tx
async def charge_tokens(
    accounts: Sequence[ChargeAccount],
    day: date,
    tokens: int,
    session: AsyncSession | None = None,
) -> None:
    """按实际 token 用量结算一次调用; 整个分配在同一个事务里完成。

    顺序固定: 免费额度(发言者 → 群) → 余额(发言者 → 群)。

    - 免费部分每个账户只扣到自己的上限, 剩下的转给下一位;
    - 免费部分不限额的账户(上层配置为 0 = 不限)意味着这次调用免费, 直接结束;
    - 余额部分: 除最后一位外只扣到可用余额(`allow_debt=False`, 不产生欠费), 最后一位承担
      剩下的全部, 因此只有它的余额可能被扣成负数(欠费) —— 一次 run 花掉多少是事后才知道的,
      与其拒绝记账, 不如如实记下欠费, 由下一次的预检拦住。
    """
    assert session is not None
    if tokens <= 0:
        return
    remaining = tokens
    for account in accounts:
        if account.free_limit is None:
            return
        if account.free_limit <= 0:
            continue
        remaining -= await spend_free(
            account.scope,
            account.scope_id,
            day,
            account.free_limit,
            remaining,
            session=session,
        )
        if remaining <= 0:
            return
    for index, account in enumerate(accounts):
        if remaining <= 0:
            return
        # 末位付款方吃掉余量(可以为负); 前面的账户最多扣到可用余额, 抢不到就把余量交下去。
        remaining -= await spend_credit(
            account.scope,
            account.scope_id,
            remaining,
            allow_debt=index == len(accounts) - 1,
            session=session,
        )


@with_session
async def get_credit(
    scope: str, scope_id: int, session: AsyncSession | None = None
) -> int:
    """账户余额; 没有行就是 0。"""
    assert session is not None
    value = await session.scalar(
        sqlalchemy.select(AgentCredit.balance).where(
            AgentCredit.scope == scope, AgentCredit.scope_id == scope_id
        )
    )
    return value or 0


@with_tx
async def adjust_credits(
    scope: str,
    scope_id: int,
    delta: int,
    reason: str,
    ref: str | None = None,
    session: AsyncSession | None = None,
) -> int:
    """增减余额并记流水(行不存在则创建), 返回新余额。

    单条 UPDATE + RETURNING, 并发调整不会丢更新。
    `ref` 为将来的支付回调提供幂等键: 同一账户同一 ref 只应入账一次,
    唯一约束会拦下重复写入。余额允许为负, 所以补发一笔小于欠费金额的额度会留下
    一部分欠费 —— 这正是想要的: 面板显示的就是实际欠了多少。
    """
    assert session is not None
    await _ensure_credit_row(session, scope, scope_id)
    balance = await session.scalar(
        sqlalchemy.update(AgentCredit)
        .where(AgentCredit.scope == scope, AgentCredit.scope_id == scope_id)
        .values(balance=AgentCredit.balance + delta)
        .returning(AgentCredit.balance)
        .execution_options(synchronize_session=False)
    )
    assert balance is not None
    session.add(
        AgentCreditLedger(
            scope=scope,
            scope_id=scope_id,
            delta=delta,
            balance_after=balance,
            reason=reason,
            ref=ref,
        )
    )
    return balance


async def set_credit(
    scope: str, scope_id: int, balance: int, reason: str = CREDIT_REASON_ADMIN
) -> int:
    """把余额设成绝对值, 返回改前的余额(面板数字字段用; 差额记进流水)。"""
    current = await get_credit(scope, scope_id)
    if current == balance:
        return current
    await adjust_credits(scope, scope_id, balance - current, reason)
    return current


__all__ = [
    "CREDIT_REASON_ADMIN",
    "CREDIT_REASON_USAGE",
    "SCOPE_CHAT",
    "SCOPE_USER",
    "ChargeAccount",
    "adjust_credits",
    "charge_tokens",
    "get_credit",
    "get_usage",
    "record_usage",
    "set_credit",
    "spend_credit",
    "spend_free",
    "utc_day",
]
