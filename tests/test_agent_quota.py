"""Agent call quota: the per-account gate in front of every model run.

Two things are worth pinning here. First, the charge order - a member's own free
allowance, then the chat's shared pool, then either balance - because it decides who
pays and is the only thing standing between a group and an unlimited model bill.
Second, that the charge is atomic: ten concurrent calls against a budget of three must
leave exactly three charges, not ten, and not zero.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import cast

import pyrogram.enums
import pyrogram.types
import pytest
from pydantic_ai.usage import RunUsage
from sqlalchemy import delete

from kmua import database
from kmua.common.memory_store import memttlcache
from kmua.config import app_config
from kmua.database.db import AsyncSessionFactory
from kmua.database.models import (
    AgentCredit,
    AgentCreditLedger,
    AgentUsageDaily,
    ChatPolicy,
)
from kmua.plugins.agent import quota, runner
from kmua.webapp.ratelimit import write_limiter
from tests.webapp_helpers import api_client, bearer, make_user, set_owners

pytestmark = pytest.mark.usefixtures("initialised_db")

OWNER_ID = 930_001
GLOBAL_ADMIN_ID = 930_002
PLAIN_ID = 930_003
OTHER_ID = 930_004

GROUP_ID = -1009300001
OTHER_GROUP_ID = -1009300002


@pytest.fixture(autouse=True)
async def clean_quota():
    """Empty the quota tables, the chat policies and the in-memory markers."""
    for row, _ in await database.get_chat_policies():
        await database.delete_chat_policy(row.chat_id)
    async with AsyncSessionFactory() as session:
        async with session.begin():
            await session.execute(delete(AgentUsageDaily))
            await session.execute(delete(AgentCredit))
            await session.execute(delete(AgentCreditLedger))
    await memttlcache.cache.clear()
    write_limiter.reset(limit_key(OWNER_ID))
    write_limiter.reset(limit_key(GLOBAL_ADMIN_ID))
    yield


def limit_key(user_id: int) -> str:
    """The rate-limit bucket `client_key` builds for the in-process test client."""
    return f"127.0.0.1:{user_id}"


def group_subject(
    user_id: int | None = PLAIN_ID, chat_id: int = GROUP_ID
) -> quota.Subject:
    return quota.Subject(user_id=user_id, chat_id=chat_id, in_group=True)


def group_message(
    chat_id: int = GROUP_ID,
    *,
    user_id: int | None = PLAIN_ID,
    sender_chat_id: int | None = None,
) -> pyrogram.types.Message:
    """A message-double good enough for `subject_of`, which reads three fields.

    Typed as the real thing so the call sites need no ignore; what it stands in for
    is Telegram's own object, which a test cannot construct.
    """
    return cast(
        pyrogram.types.Message,
        SimpleNamespace(
            chat=SimpleNamespace(id=chat_id, type=pyrogram.enums.ChatType.SUPERGROUP),
            sender_chat=(
                None if sender_chat_id is None else SimpleNamespace(id=sender_chat_id)
            ),
            from_user=None if user_id is None else SimpleNamespace(id=user_id),
        ),
    )


async def ledger_rows(scope: str, scope_id: int) -> list[AgentCreditLedger]:
    async with AsyncSessionFactory() as session:
        result = await session.execute(
            AgentCreditLedger.__table__.select()
            .where(
                AgentCreditLedger.scope == scope,
                AgentCreditLedger.scope_id == scope_id,
            )
            .order_by(AgentCreditLedger.id)
        )
        return [AgentCreditLedger(**row._mapping) for row in result.all()]


async def usage_rows() -> list[AgentUsageDaily]:
    async with AsyncSessionFactory() as session:
        result = await session.execute(AgentUsageDaily.__table__.select())
        return [AgentUsageDaily(**row._mapping) for row in result.all()]


# ------------------------------------------------------------------- identity


def test_identity_resolution():
    """Who pays is decided by `sender_chat`, matching the middleware's own rule."""
    real = group_message()
    assert quota.subject_of(real).accounts() == [
        (database.SCOPE_USER, PLAIN_ID),
        (database.SCOPE_CHAT, GROUP_ID),
    ]

    # Anonymous admin: the pseudo-user id is present, but `sender_chat` is the group.
    anon = group_message(user_id=1087968824, sender_chat_id=GROUP_ID)
    assert quota.subject_of(anon).accounts() == [(database.SCOPE_CHAT, GROUP_ID)]

    # A channel posting into the group has no user identity at all.
    channel = group_message(user_id=None, sender_chat_id=-1009300999)
    assert quota.subject_of(channel).accounts() == [(database.SCOPE_CHAT, GROUP_ID)]

    # Private chat: the chat *is* the user, so charging both would double-bill.
    private = cast(
        pyrogram.types.Message,
        SimpleNamespace(
            chat=SimpleNamespace(id=PLAIN_ID, type=pyrogram.enums.ChatType.PRIVATE),
            sender_chat=None,
            from_user=SimpleNamespace(id=PLAIN_ID),
        ),
    )
    assert quota.subject_of(private).accounts() == [(database.SCOPE_USER, PLAIN_ID)]


# ------------------------------------------------------------------ settlement


async def test_free_allowance_is_spent_by_tokens_then_refuses(monkeypatch):
    monkeypatch.setattr(app_config, "agent_quota_free_daily_tokens", 100, raising=False)
    subject = group_subject()

    assert await quota.can_start(subject) is True
    await quota.settle(subject, RunUsage(input_tokens=60, output_tokens=30))

    _, free_used, input_tokens, output_tokens = await database.get_usage(
        database.SCOPE_USER, PLAIN_ID, database.utc_day()
    )
    assert (free_used, input_tokens, output_tokens) == (90, 60, 30)
    assert await quota.can_start(subject) is True  # 10 tokens left

    await quota.settle(subject, RunUsage(input_tokens=50, output_tokens=10))

    # 用超了: 免费额度只扣到上限, 下一次预检开始拒绝。
    _, free_used, _, _ = await database.get_usage(
        database.SCOPE_USER, PLAIN_ID, database.utc_day()
    )
    assert free_used == 100
    assert await quota.can_start(subject) is False


async def test_a_short_chat_costs_less_than_a_long_task(monkeypatch):
    """The point of metering tokens: a 200-token turn buys many more runs than a
    turn that burns 50k tokens."""
    monkeypatch.setattr(
        app_config, "agent_quota_free_daily_tokens", 10_000, raising=False
    )
    chatty = group_subject(PLAIN_ID)
    heavy = group_subject(OTHER_ID)

    for _ in range(4):
        assert await quota.can_start(chatty) is True
        await quota.settle(chatty, RunUsage(input_tokens=150, output_tokens=50))

    _, free_used, _, _ = await database.get_usage(
        database.SCOPE_USER, PLAIN_ID, database.utc_day()
    )
    assert free_used == 800  # 4 x 200 tokens, most of the 10k allowance left

    assert await quota.can_start(heavy) is True
    await quota.settle(heavy, RunUsage(input_tokens=49_000, output_tokens=1_000))

    # One long task exhausted the whole allowance and went into debt.
    assert await quota.can_start(heavy) is False


async def test_group_pool_covers_members_after_their_own_allowance(monkeypatch):
    monkeypatch.setattr(app_config, "agent_quota_free_daily_tokens", 100, raising=False)
    await database.set_chat_policy(GROUP_ID, ChatPolicy(agent_quota_daily_tokens=500))
    subject = group_subject()

    # 250 tokens: 个人出满 100, 剩下的 150 由群池接。
    await quota.settle(subject, RunUsage(input_tokens=200, output_tokens=50))

    _, user_free, _, _ = await database.get_usage(
        database.SCOPE_USER, PLAIN_ID, database.utc_day()
    )
    _, chat_free, _, _ = await database.get_usage(
        database.SCOPE_CHAT, GROUP_ID, database.utc_day()
    )
    assert user_free == 100
    assert chat_free == 150

    # 个人额度已空, 但群池还有 350 → 仍然放行。
    assert await quota.can_start(subject) is True


async def test_anonymous_sender_uses_the_chat_pool_and_is_refused_without_one():
    anonymous = group_subject(user_id=None)

    # 没有个人账户, 群也没配额度: 直接拒绝。
    assert await quota.can_start(anonymous) is False

    await database.set_chat_policy(GROUP_ID, ChatPolicy(agent_quota_daily_tokens=300))
    assert await quota.can_start(anonymous) is True

    await quota.settle(anonymous, RunUsage(input_tokens=100, output_tokens=100))
    _, chat_free, _, _ = await database.get_usage(
        database.SCOPE_CHAT, GROUP_ID, database.utc_day()
    )
    assert chat_free == 200


async def test_concurrent_settles_neither_overspend_nor_lose_tokens(monkeypatch):
    """Concurrent settlement must respect the allowance cap and still account for
    every token that was actually used."""
    monkeypatch.setattr(app_config, "agent_quota_free_daily_tokens", 100, raising=False)
    subject = group_subject()
    runs, tokens_each = 10, 40

    await asyncio.gather(
        *(
            quota.settle(
                subject,
                RunUsage(input_tokens=tokens_each - 10, output_tokens=10),
            )
            for _ in range(runs)
        )
    )

    _, free_used, _, _ = await database.get_usage(
        database.SCOPE_USER, PLAIN_ID, database.utc_day()
    )
    chat_credit = await database.get_credit(database.SCOPE_CHAT, GROUP_ID)
    assert free_used <= 100  # 免费额度从不过冲
    # 本次调用涉及的每个账户都被算到: 花掉的 token 总量一分不少。
    assert free_used + (-chat_credit) == runs * tokens_each


async def test_a_contended_non_last_payer_never_falls_into_debt(monkeypatch):
    """发言者是"非末位付款方", 并发结算时它的余额永远不能被扣成欠费。

    一个用户在多个群同时说话, 或者多个成员共用一个群账户, 都会让同一个账户被并发划扣。
    """
    monkeypatch.setattr(app_config, "agent_quota_free_daily_tokens", 1, raising=False)
    user_credit, chat_credit, tokens_each, runs = 150, 50, 80, 3
    await database.adjust_credits(
        database.SCOPE_USER, PLAIN_ID, user_credit, database.CREDIT_REASON_ADMIN
    )
    await database.adjust_credits(
        database.SCOPE_CHAT, GROUP_ID, chat_credit, database.CREDIT_REASON_ADMIN
    )
    subject = group_subject()
    # 先把免费额度用干, 之后的每一次都只能走余额。
    await quota.settle(subject, RunUsage(input_tokens=1, output_tokens=0))

    await asyncio.gather(
        *(
            quota.settle(subject, RunUsage(input_tokens=tokens_each, output_tokens=0))
            for _ in range(runs)
        )
    )

    user = await database.get_credit(database.SCOPE_USER, PLAIN_ID)
    chat = await database.get_credit(database.SCOPE_CHAT, GROUP_ID)
    assert user >= 0, "非末位付款方被扣成了欠费"
    assert (user_credit - user) + (chat_credit - chat) == runs * tokens_each


# ------------------------------------------------------------------ exemption


async def test_exempt_chat_is_never_charged():
    await database.set_chat_policy(GROUP_ID, ChatPolicy(agent_quota_exempt=True))

    assert await quota.can_start(group_subject()) is True
    await quota.settle(group_subject(), RunUsage(input_tokens=5000, output_tokens=5000))

    assert await usage_rows() == []
    assert await database.get_credit(database.SCOPE_USER, PLAIN_ID) == 0


async def test_owner_and_global_admin_are_exempt(monkeypatch):
    monkeypatch.setattr(app_config, "owners", [OWNER_ID], raising=False)
    await make_user(GLOBAL_ADMIN_ID, full_name="Admin", global_admin=True)

    for user_id in (OWNER_ID, GLOBAL_ADMIN_ID):
        subject = group_subject(user_id)
        assert await quota.can_start(subject) is True
        await quota.settle(subject, RunUsage(input_tokens=9999, output_tokens=9999))

    assert await usage_rows() == []


async def test_zero_free_daily_means_unlimited_but_still_metered(monkeypatch):
    """0 = no cap, not "no accounting": nothing is charged, usage is still recorded
    so an operator can see what the deployment actually spends."""
    monkeypatch.setattr(app_config, "agent_quota_free_daily_tokens", 0, raising=False)
    subject = group_subject()

    for _ in range(5):
        assert await quota.can_start(subject) is True
        await quota.settle(subject, RunUsage(input_tokens=10_000, output_tokens=10_000))

    assert await database.get_credit(database.SCOPE_USER, PLAIN_ID) == 0
    assert await database.get_credit(database.SCOPE_CHAT, GROUP_ID) == 0
    for scope, scope_id in subject.accounts():
        requests, free_used, input_tokens, output_tokens = await database.get_usage(
            scope, scope_id, database.utc_day()
        )
        assert (requests, free_used, input_tokens, output_tokens) == (
            5,
            0,
            50_000,
            50_000,
        )


# -------------------------------------------------------------------- credits


async def test_credits_take_over_when_free_is_gone(monkeypatch):
    monkeypatch.setattr(app_config, "agent_quota_free_daily_tokens", 100, raising=False)
    await database.adjust_credits(
        database.SCOPE_USER, PLAIN_ID, 400, database.CREDIT_REASON_ADMIN
    )
    subject = group_subject()

    await quota.settle(subject, RunUsage(input_tokens=80, output_tokens=20))
    assert await database.get_credit(database.SCOPE_USER, PLAIN_ID) == 400

    await quota.settle(subject, RunUsage(input_tokens=200, output_tokens=50))

    assert await database.get_credit(database.SCOPE_USER, PLAIN_ID) == 150
    rows = await ledger_rows(database.SCOPE_USER, PLAIN_ID)
    assert [(row.delta, row.reason) for row in rows] == [
        (400, database.CREDIT_REASON_ADMIN),
        (-250, database.CREDIT_REASON_USAGE),
    ]


async def test_a_single_run_may_overshoot_into_debt(monkeypatch):
    """Token usage is only known once the run ends, so the overshoot is recorded
    honestly instead of being refused - and it blocks the next call."""
    monkeypatch.setattr(app_config, "agent_quota_free_daily_tokens", 100, raising=False)
    subject = group_subject()

    await quota.settle(subject, RunUsage(input_tokens=1_000, output_tokens=0))

    assert await database.get_credit(database.SCOPE_USER, PLAIN_ID) == 0
    # 群账户是最后一位付款方, 承担超出的 900。
    assert await database.get_credit(database.SCOPE_CHAT, GROUP_ID) == -900

    # 运维补发 500 之后仍欠 400: 依然拒绝。
    await database.adjust_credits(
        database.SCOPE_CHAT, GROUP_ID, 500, database.CREDIT_REASON_ADMIN
    )
    assert await quota.can_start(subject) is False
    # 补到正好归零: 欠费结清, 但仍没有可花的额度。
    await database.adjust_credits(
        database.SCOPE_CHAT, GROUP_ID, 400, database.CREDIT_REASON_ADMIN
    )
    assert await quota.can_start(subject) is False
    # 再补 1000 才有得花; 预检立刻放行, 不等任何缓存过期。
    await database.adjust_credits(
        database.SCOPE_CHAT, GROUP_ID, 1_000, database.CREDIT_REASON_ADMIN
    )
    assert await quota.can_start(subject) is True


async def test_status_text_reports_the_user_and_chat_accounts(monkeypatch):
    """/quota is the only way a user can see why they were refused."""
    monkeypatch.setattr(
        app_config, "agent_quota_free_daily_tokens", 100_000, raising=False
    )
    await database.set_chat_policy(
        GROUP_ID, ChatPolicy(agent_quota_daily_tokens=20_000)
    )

    await quota.settle(
        group_subject(), RunUsage(input_tokens=5_000, output_tokens=1_000)
    )
    text = quota.status_text(await quota.get_state(group_subject()), "zh-CN")

    assert "今日 AI 用量: 1 次 / 6.0k tokens" in text
    assert "免费额度: 6.0k/100.0k tokens" in text
    assert "本群额度" in text

    # A private chat has no second account, so no chat line appears.
    private = quota.Subject(user_id=PLAIN_ID, chat_id=PLAIN_ID, in_group=False)
    private_text = quota.status_text(await quota.get_state(private), "zh-CN")
    assert "本群额度" not in private_text


async def test_status_text_keeps_the_chat_line_when_the_user_is_uncapped(monkeypatch):
    """Personal quota unlimited must not swallow the chat's line: in a group that is
    the only place the user can see what the group still has."""
    monkeypatch.setattr(app_config, "agent_quota_free_daily_tokens", 0, raising=False)
    await database.set_chat_policy(GROUP_ID, ChatPolicy(agent_quota_daily_tokens=5_000))
    subject = group_subject()

    text = quota.status_text(await quota.get_state(subject), "zh-CN")

    assert "没有用量限制" in text
    assert "本群额度" in text


async def test_usage_records_tokens_on_every_account(monkeypatch):
    """A member paid by the chat pool still shows up in their own usage."""
    monkeypatch.setattr(app_config, "agent_quota_free_daily_tokens", 100, raising=False)
    await database.set_chat_policy(GROUP_ID, ChatPolicy(agent_quota_daily_tokens=500))
    subject = group_subject()

    await quota.settle(subject, RunUsage(input_tokens=200, output_tokens=50))

    for scope, scope_id in subject.accounts():
        requests, _, input_tokens, output_tokens = await database.get_usage(
            scope, scope_id, database.utc_day()
        )
        assert (requests, input_tokens, output_tokens) == (1, 200, 50)


# ---------------------------------------------------------------------- panel


async def test_panel_grants_credits_and_reports_quota(monkeypatch):
    set_owners(monkeypatch, [OWNER_ID])
    await make_user(OWNER_ID, full_name="Owner")
    await make_user(GLOBAL_ADMIN_ID, full_name="Admin", global_admin=True)
    await make_user(PLAIN_ID, full_name="Plain")

    async with api_client() as client:
        granted = await client.patch(
            f"/api/admin/users/{PLAIN_ID}",
            headers=bearer(OWNER_ID),
            json={"agent_credits": 5},
        )
        refused = await client.patch(
            f"/api/admin/users/{PLAIN_ID}",
            headers=bearer(GLOBAL_ADMIN_ID),
            json={"agent_credits": 99},
        )

    assert granted.status_code == 200
    body = granted.json()
    assert body["user"]["agent_quota"]["credits"] == 5
    assert [change["field"] for change in body["changed"]] == ["agent_credits"]
    assert await database.get_credit(database.SCOPE_USER, PLAIN_ID) == 5
    rows = await ledger_rows(database.SCOPE_USER, PLAIN_ID)
    assert [(row.delta, row.reason) for row in rows] == [
        (5, database.CREDIT_REASON_ADMIN)
    ]

    assert refused.status_code == 200
    assert [item["field"] for item in refused.json()["skipped"]] == ["agent_credits"]
    assert await database.get_credit(database.SCOPE_USER, PLAIN_ID) == 5


async def test_panel_sets_chat_quota_fields(monkeypatch):
    set_owners(monkeypatch, [OWNER_ID])
    await make_user(OWNER_ID, full_name="Owner")
    await make_user(GLOBAL_ADMIN_ID, full_name="Admin", global_admin=True)

    async with api_client() as client:
        written = await client.put(
            f"/api/admin/chat-policies/{GROUP_ID}",
            headers=bearer(OWNER_ID),
            json={
                "agent_quota_daily_tokens": 7,
                "agent_quota_exempt": True,
                "agent_credits": 9,
            },
        )
        detail = await client.get(
            f"/api/admin/chat-policies/{GROUP_ID}", headers=bearer(OWNER_ID)
        )
        refused = await client.put(
            f"/api/admin/chat-policies/{GROUP_ID}",
            headers=bearer(GLOBAL_ADMIN_ID),
            json={"agent_quota_daily_tokens": 1},
        )

    assert written.status_code == 200
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["item"]["policy"]["agent_quota_daily_tokens"] == 7
    assert payload["item"]["policy"]["agent_quota_exempt"] is True
    assert payload["agent_quota"]["credits"] == 9
    assert await database.get_credit(database.SCOPE_CHAT, GROUP_ID) == 9
    assert refused.status_code == 403


async def test_a_chat_credit_grant_is_audited_on_its_own(monkeypatch):
    """额度不在 policy 里, 所以纯发放额度的请求不会产生 policy 差异 —— 它仍然必须留下
    一条指名道姓的审计记录, 否则运维给某个群发钱这件事无处可查。"""
    from kmua.webapp import audit

    set_owners(monkeypatch, [OWNER_ID])
    await make_user(OWNER_ID, full_name="Owner")
    await database.set_chat_policy(GROUP_ID, ChatPolicy())

    records: list[str] = []

    class _Sink:
        @staticmethod
        def warning(message: str) -> None:
            records.append(message)

    original = audit.logger
    audit.logger = _Sink  # type: ignore[assignment]
    try:
        async with api_client() as client:
            response = await client.put(
                f"/api/admin/chat-policies/{GROUP_ID}",
                headers=bearer(OWNER_ID),
                json={"agent_credits": 500_000},
            )
    finally:
        audit.logger = original

    assert response.status_code == 200
    assert await database.get_credit(database.SCOPE_CHAT, GROUP_ID) == 500_000
    assert len(records) == 1
    assert "chat.policy.update" in records[0]
    assert str(OWNER_ID) in records[0]
    assert "agent_credits" in records[0]
    assert "500000" in records[0]


# --------------------------------------------------------------------- runner


class _ReplyMessage:
    chat = SimpleNamespace(id=GROUP_ID, type=pyrogram.enums.ChatType.SUPERGROUP)

    def __init__(self) -> None:
        self.replies: list[str] = []

    async def reply_text(self, text: str, **kwargs: object) -> None:
        self.replies.append(text)


async def _run(message: _ReplyMessage, subject: quota.Subject) -> None:
    await runner.run_agent(  # type: ignore[arg-type]
        agi=object(),  # type: ignore[arg-type]
        client=SimpleNamespace(),  # type: ignore[arg-type]
        message=message,  # type: ignore[arg-type]
        user_id=subject.user_id or 0,
        chat_id=subject.chat_id or 0,
        user_prompt=[],
        history=[],
        deps=SimpleNamespace(),
        multimodal_model=None,
        model=None,
        lang="zh-CN",
        subject=subject,
    )


async def test_run_agent_refuses_when_exhausted_without_calling_the_model(
    monkeypatch,
):
    monkeypatch.setattr(app_config, "agent_quota_free_daily_tokens", 10, raising=False)
    monkeypatch.setattr(app_config, "agent_run_timeout", 0, raising=False)

    calls: list[dict] = []

    async def fake_impl(**kwargs: object) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(runner, "_run_agent_impl", fake_impl)
    subject = group_subject()
    # 花光免费额度(并欠费), 预检于是拒绝这一次。
    await quota.settle(subject, RunUsage(input_tokens=100, output_tokens=0))
    message = _ReplyMessage()

    await _run(message, subject)

    assert calls == []
    assert len(message.replies) == 1
    assert "额度" in message.replies[0]


@asynccontextmanager
async def _fake_agent_run(
    usage: RunUsage | None = None, error: Exception | None = None
):
    """A stand-in for `_iter_with_spill_session`'s AgentRun, so the REAL
    `_run_agent_impl` body (and its own settle call) can be exercised."""
    if error is not None:
        raise error

    async def _next(node: object) -> object:
        return node

    yield SimpleNamespace(
        next_node=object(),
        result=SimpleNamespace(output="hi"),
        usage=usage if usage is not None else RunUsage(),
        all_messages=lambda: [],
        next=_next,
    )


@asynccontextmanager
async def _exploding_agent_run(**_kwargs: object):
    raise RuntimeError("model exploded")
    yield  # pragma: no cover


# `use_model` is the caller-supplied model unless an override/transcription picks
# another one, so a plain object with a model name is enough for both branches.
_FAKE_MODEL = SimpleNamespace(model_name="fake-model")


def _stub_impl_environment(monkeypatch, *, streaming: bool = False) -> None:
    """Everything the real `_run_agent_impl` touches on its way to a success branch.

    `streaming` picks which of the two success branches runs; they settle separately.
    """
    monkeypatch.setattr(app_config, "agent_streaming", streaming, raising=False)
    monkeypatch.setattr(runner.Agent, "is_end_node", staticmethod(lambda _node: True))
    monkeypatch.setattr(runner, "log_run_cache_stats", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        runner, "check_needs_multimodal", lambda *_args, **_kwargs: False
    )
    monkeypatch.setattr(
        runner.provider,
        "make_chat_model",
        lambda *_args, **_kwargs: SimpleNamespace(model_name="fake-model"),
    )
    monkeypatch.setattr(
        runner.provider, "make_model_settings", lambda *_args, **_kwargs: None
    )

    async def fake_reply(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(runner, "reply_output", fake_reply)


async def _run_impl_with_stubbed_agent(
    message: _ReplyMessage, subject: quota.Subject
) -> None:
    """Drive the REAL `_run_agent_impl` so its own settle call is exercised.

    `_iter_with_spill_session` must already be patched to yield a stubbed AgentRun.
    """
    await runner._run_agent_impl(  # type: ignore[arg-type]
        **{
            "agi": object(),
            "client": SimpleNamespace(),
            "message": message,
            "user_id": subject.user_id,
            "chat_id": subject.chat_id,
            "user_prompt": [],
            "history": [],
            "deps": SimpleNamespace(multimodal_model=None, history=[]),
            "multimodal_model": None,
            "model": _FAKE_MODEL,
            "lang": "zh-CN",
            "subject": subject,
        }
    )


async def test_the_real_impl_settles_the_run_s_own_usage(monkeypatch):
    """The metering call lives inside `_run_agent_impl`, so this drives the real
    function: delete or misplace that `quota.settle(subject, agent_run.usage)` line
    and this test fails."""
    monkeypatch.setattr(
        app_config, "agent_quota_free_daily_tokens", 100_000, raising=False
    )
    _stub_impl_environment(monkeypatch)
    # `_iter_with_spill_session(agi, ...)` passes the agent positionally.
    usage = RunUsage(input_tokens=800, output_tokens=200)
    monkeypatch.setattr(
        runner,
        "_iter_with_spill_session",
        lambda *_args, **_kw: _fake_agent_run(usage=usage),
    )
    subject = group_subject()

    await _run_impl_with_stubbed_agent(_ReplyMessage(), subject)

    _, free_used, input_tokens, output_tokens = await database.get_usage(
        database.SCOPE_USER, PLAIN_ID, database.utc_day()
    )
    assert (free_used, input_tokens, output_tokens) == (1_000, 800, 200)


async def test_the_streaming_default_path_also_settles(monkeypatch):
    """`agent_streaming` defaults to True, so the streaming branch is the one a real
    deployment takes. Delete its settle call and every other test stays green while
    streamed runs become free."""
    monkeypatch.setattr(
        app_config, "agent_quota_free_daily_tokens", 100_000, raising=False
    )
    _stub_impl_environment(monkeypatch, streaming=True)
    usage = RunUsage(input_tokens=1_200, output_tokens=300)
    monkeypatch.setattr(
        runner,
        "_iter_with_spill_session",
        lambda *_args, **_kw: _fake_agent_run(usage=usage),
    )
    subject = group_subject()

    await _run_impl_with_stubbed_agent(_ReplyMessage(), subject)

    _, free_used, input_tokens, output_tokens = await database.get_usage(
        database.SCOPE_USER, PLAIN_ID, database.utc_day()
    )
    assert (free_used, input_tokens, output_tokens) == (1_500, 1_200, 300)


async def test_a_run_is_charged_even_when_post_run_bookkeeping_fails(monkeypatch):
    """The history cache, the coverage advance and the cache-stats log all run after the
    answer was delivered and can raise. The tokens are already spent, so the charge must
    not depend on them."""
    monkeypatch.setattr(
        app_config, "agent_quota_free_daily_tokens", 100_000, raising=False
    )
    _stub_impl_environment(monkeypatch)
    usage = RunUsage(input_tokens=700, output_tokens=100)

    def boom(*_args: object, **_kwargs: object) -> None:
        raise AttributeError("'NoneType' object has no attribute 'model_name'")

    monkeypatch.setattr(runner, "log_run_cache_stats", boom)
    monkeypatch.setattr(
        runner,
        "_iter_with_spill_session",
        lambda *_args, **_kw: _fake_agent_run(usage=usage),
    )
    subject = group_subject()

    await _run_impl_with_stubbed_agent(_ReplyMessage(), subject)

    _, free_used, input_tokens, output_tokens = await database.get_usage(
        database.SCOPE_USER, PLAIN_ID, database.utc_day()
    )
    assert (free_used, input_tokens, output_tokens) == (800, 700, 100)


async def test_a_run_that_raises_is_never_charged(monkeypatch):
    """An errored run reaches no success branch, so nothing is metered: there is no
    charge to refund. The failure reply is the implementation's business."""
    monkeypatch.setattr(
        app_config, "agent_quota_free_daily_tokens", 100_000, raising=False
    )
    _stub_impl_environment(monkeypatch)
    monkeypatch.setattr(runner, "_iter_with_spill_session", _exploding_agent_run)
    subject = group_subject()

    await _run_impl_with_stubbed_agent(_ReplyMessage(), subject)

    assert await usage_rows() == []
    assert await database.get_credit(database.SCOPE_USER, PLAIN_ID) == 0


async def test_whitelist_wins_over_quota(monkeypatch):
    """With the whitelist on, an unlisted group is refused silently - no charge, no notice.

    The subject is drained first: with quota to spare the precheck passes either way,
    so the test would not notice the two gates being swapped.
    """
    monkeypatch.setattr(app_config, "agent_whitelist_mode", True, raising=False)
    monkeypatch.setattr(app_config, "agent_run_timeout", 0, raising=False)
    monkeypatch.setattr(app_config, "agent_quota_free_daily_tokens", 1, raising=False)
    from kmua.database import chat_policy as store

    store._set_agent_cache(set())

    called: list[dict] = []

    async def fake_impl(**kwargs: object) -> None:
        called.append(kwargs)

    monkeypatch.setattr(runner, "_run_agent_impl", fake_impl)
    subject = group_subject(chat_id=OTHER_GROUP_ID)
    await quota.settle(subject, RunUsage(input_tokens=1, output_tokens=0))
    assert await quota.can_start(subject) is False  # quota alone would refuse this
    message = _ReplyMessage()

    await _run(message, subject)

    assert called == []
    # 白名单先判: 没资格用 agent 的群不该收到额度提示(顺序反了这里就会多一条提示)。
    assert message.replies == []


async def test_an_absolute_set_survives_a_settlement_in_the_same_window(monkeypatch):
    """The panel writes an absolute balance, and both the audit record and the operator's
    intent say "this account now holds exactly N". A delta computed from a read taken
    outside the writing transaction would leave the account at N - settled while the
    audit still claims N.

    The hook fires where `set_credit` secures the row, i.e. inside its transaction and
    before it reads the balance; a read taken before that point gets the stale value.
    """
    from kmua.database import agent_quota as aq

    await database.set_credit(database.SCOPE_USER, PLAIN_ID, 500)
    original = aq._ensure_credit_row
    fired: list[int] = []

    async def ensure_then_settle(session, scope, scope_id):
        await original(session, scope, scope_id)
        if fired:
            return
        fired.append(1)
        await database.spend_credit(database.SCOPE_USER, PLAIN_ID, 300)

    monkeypatch.setattr(aq, "_ensure_credit_row", ensure_then_settle)

    previous = await database.set_credit(database.SCOPE_USER, PLAIN_ID, 1_000)

    # The settlement went first, so the balance really was 200 when the write happened:
    # the audit pair (old=200, new=1000) matches reality. Read outside the transaction and
    # the pair becomes (old=500, new=1000) while the row lands on 700.
    assert previous == 200
    assert await database.get_credit(database.SCOPE_USER, PLAIN_ID) == 1_000
