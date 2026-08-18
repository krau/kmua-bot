"""新成员验证: 纯函数 + DAO + sweep, 不需要 Telegram 连接。

sweep 用例通过替换 `verify.client` 为记录调用的假对象, 覆盖三种失败路径
(kick/ban/unrestrict)、群停用取消与孤儿会话清理。
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from pyrogram.enums import ButtonStyle
from pyrogram.errors import RPCError

from kmua import database
from kmua.database.models import ChatConfig, VerificationSession
from kmua.i18n import i18n
from kmua.plugins.verify import challenge, session
from tests.webapp_helpers import make_chat

pytestmark = pytest.mark.usefixtures("initialised_db")


@pytest.fixture(autouse=True)
async def clean_verify():
    """清空会话表与内存注册表, 保持测试隔离。"""
    for row in await database.get_all_verification_sessions():
        await database.delete_verification_session(row.id)
    session._sessions.clear()
    session._by_user.clear()
    yield


# ------------------------------------------------------------------ 纯函数


def _verify_ctx(**overrides) -> challenge.VerifyContext:
    from pyrogram.types import User

    base = {
        "chat_id": -100_910_001,
        "user": User(id=1, first_name="T", is_bot=False),
        "is_join": False,
    }
    base.update(overrides)
    return challenge.VerifyContext(**base)


def test_strategy_matches():
    # all: 只在入群命中, 与验证状态无关
    assert challenge.strategy_matches("all", _verify_ctx(is_join=True)) is True
    assert challenge.strategy_matches("all", _verify_ctx(is_join=False)) is False
    assert (
        challenge.strategy_matches("all", _verify_ctx(is_join=False, is_verified=True))
        is False
    )
    # first_message: 首次发言命中; 已验证/验证中跳过; 入群不触发
    assert (
        challenge.strategy_matches("first_message", _verify_ctx(is_join=False)) is True
    )
    assert (
        challenge.strategy_matches(
            "first_message", _verify_ctx(is_join=False, is_verified=True)
        )
        is False
    )
    assert (
        challenge.strategy_matches(
            "first_message", _verify_ctx(is_join=False, has_active_session=True)
        )
        is False
    )
    assert (
        challenge.strategy_matches("first_message", _verify_ctx(is_join=True)) is False
    )
    # 未知策略不验证
    assert challenge.strategy_matches("unknown", _verify_ctx(is_join=True)) is False


def test_make_challenge_payload_dispatch():
    assert "answer" in challenge.make_challenge_payload("math_easy", [])
    assert "question" in challenge.make_challenge_payload("math_hard", [])
    assert "target" in challenge.make_challenge_payload("emoji", [])
    assert challenge.make_challenge_payload("sticker", []) == {}
    qa = challenge.make_challenge_payload("custom_qa", [])
    assert "question" in qa and "answers" in qa
    fallback = challenge.make_challenge_payload("unknown_method", [])
    assert "question" in fallback and "answers" in fallback


def test_math_hard_challenge_shape():
    """高等数学随机题: 4 个互异选项、答案在选项中、题目非空且含公式/记号。"""
    markers = (
        "$",
        "det",
        "特征值",
        "可逆",
        "对角化",
        "tr(",
        "零空间",
        "列空间",
        "rank",
        "E[",
        "Var",
        "蒙提霍尔",
        "切比雪夫",
        "∫",
        "lim",
    )
    for _ in range(200):
        payload = challenge.make_math_hard_challenge()
        assert len(payload["options"]) == 4
        assert len(set(payload["options"])) == 4
        assert payload["answer"] in payload["options"]
        assert payload["question"]
        assert any(m in payload["question"] for m in markers)


def test_math_hard_is_correct_option():
    session = _session_with(
        "math_hard",
        {
            "question": "$\\binom{5}{2}$",
            "answer": "10",
            "options": ["10", "7", "20", "25"],
        },
    )
    assert challenge._is_correct_option(session, 0) is True
    assert challenge._is_correct_option(session, 1) is False
    assert challenge._is_multi_answer(session) is False


def test_math_challenge_shape():
    for _ in range(200):
        payload = challenge.make_math_challenge()
        assert len(payload["options"]) == 4
        assert len(set(payload["options"])) == 4
        assert payload["answer"] in payload["options"]
        assert payload["answer"] == payload["a"] + payload["b"]
        assert 2 <= payload["a"] <= 9
        assert 2 <= payload["b"] <= 9


def test_emoji_challenge_shape():
    for _ in range(200):
        payload = challenge.make_emoji_challenge()
        assert len(payload["options"]) == 6
        assert payload["target"] in payload["options"]


def test_sticker_challenge():
    assert challenge.make_sticker_challenge() == {}


def test_to_rich_html_converts_newlines():
    assert session._to_rich_html("a\nb\n\nc") == "a<br>b<br><br>c"
    assert session._to_rich_html("no newline") == "no newline"


def test_qa_challenge_custom_and_default():
    custom = [
        {
            "question": "Q1?",
            "options": ["a", "b", "c"],
            "answers": ["a", "c"],
            "select": "any",
        },
        {"question": "Q2?", "options": ["a", "b"], "answers": ["a"]},
    ]
    for _ in range(50):
        payload = challenge.make_qa_challenge(custom)
        assert payload["question"] in ("Q1?", "Q2?")
        assert set(payload["answers"]) <= set(payload["options"])
        assert payload["select"] in ("any", "all")
        if payload["question"] == "Q1?":
            assert payload["select"] == "any"
    for _ in range(50):
        payload = challenge.make_qa_challenge([])
        assert {"question", "options", "answers", "select"} <= set(payload)
        assert payload["select"] in ("any", "all")
        assert len(payload["answers"]) >= 1
        assert all(answer in payload["options"] for answer in payload["answers"])
        assert len(payload["options"]) >= 2


def test_qa_challenge_falls_back_for_legacy_or_broken_questions():
    """旧格式(无 options/answers)或残缺条目应被跳过, 退回默认题库。"""
    for broken in (
        [{"question": "Q?", "answers": ["a", "b"]}],
        [{"question": "Q?", "options": ["a", "b"], "answers": ["c"]}],
        [{"question": "", "options": ["a", "b"], "answers": ["a"]}],
        [{"question": "Q?", "options": ["a"], "answers": ["a"]}],
        [{"question": "Q?", "options": ["a", "b"], "answers": []}],
    ):
        payload = challenge.make_qa_challenge(broken)
        assert {"question", "options", "answers"} <= set(payload)
        assert all(answer in payload["options"] for answer in payload["answers"])


def _session_with(method: str, payload: dict) -> VerificationSession:
    return VerificationSession(
        chat_id=-100_910_001, user_id=1, method=method, payload=payload
    )


def test_multi_answer_detection():
    multi = _session_with(
        "custom_qa",
        {
            "question": "Q",
            "options": ["a", "b"],
            "answers": ["a", "b"],
            "select": "all",
        },
    )
    any_of = _session_with(
        "custom_qa",
        {
            "question": "Q",
            "options": ["a", "b"],
            "answers": ["a", "b"],
            "select": "any",
        },
    )
    legacy_multi = _session_with(
        "custom_qa", {"question": "Q", "options": ["a", "b"], "answers": ["a", "b"]}
    )
    single = _session_with(
        "custom_qa", {"question": "Q", "options": ["a", "b"], "answers": ["a"]}
    )
    math_session = _session_with("math_easy", {"answer": 5, "options": [1, 5, 3, 4]})
    assert challenge._is_multi_answer(multi) is True
    assert challenge._is_multi_answer(legacy_multi) is True  # 缺省 select 按全选
    assert challenge._is_multi_answer(any_of) is False  # 任选其一不走勾选流程
    assert challenge._is_multi_answer(single) is False
    assert challenge._is_multi_answer(math_session) is False
    assert challenge._is_multi_answer(math_session) is False


def test_is_correct_option():
    multi = _session_with(
        "custom_qa",
        {"question": "Q", "options": ["a", "b", "c"], "answers": ["a", "c"]},
    )
    single = _session_with(
        "custom_qa", {"question": "Q", "options": ["a", "b"], "answers": ["a"]}
    )
    math_session = _session_with("math_easy", {"answer": 5, "options": [1, 5, 3, 4]})
    emoji_session = _session_with("emoji", {"target": "🍎", "options": ["🍎", "🍌"]})
    assert challenge._is_correct_option(multi, 0) is True
    assert challenge._is_correct_option(multi, 1) is False
    assert challenge._is_correct_option(multi, 2) is True
    assert challenge._is_correct_option(multi, 9) is False
    any_of = _session_with(
        "custom_qa",
        {
            "question": "Q",
            "options": ["a", "b", "c"],
            "answers": ["a", "c"],
            "select": "any",
        },
    )
    assert challenge._is_correct_option(single, 0) is True
    assert challenge._is_correct_option(any_of, 0) is True  # 任选其一: 任一正确项即中
    assert challenge._is_correct_option(any_of, 2) is True
    assert challenge._is_correct_option(any_of, 1) is False
    assert challenge._is_correct_option(math_session, 1) is True
    assert challenge._is_correct_option(emoji_session, 0) is True
    assert challenge._is_correct_option(emoji_session, 1) is False


def test_challenge_markup_multi_has_submit_and_selected_marks():
    multi = _session_with(
        "custom_qa",
        {
            "question": "Q",
            "options": ["a", "b", "c"],
            "answers": ["a", "c"],
            "selected": [0],
        },
    )
    multi.id = 1
    markup = challenge._challenge_markup(multi, "zh-CN")
    callbacks = [
        str(b.callback_data or "") for row in markup.inline_keyboard for b in row
    ]
    labels = [b.text for row in markup.inline_keyboard for b in row]
    assert "verify:1:submit" in callbacks
    assert "a (已选)" in labels
    assert "b" in labels and "b (已选)" not in labels
    # 管理员按钮带颜色: 放行绿, 封禁红
    buttons = {b.callback_data: b for row in markup.inline_keyboard for b in row}
    assert buttons["verify_admin:1:approve"].style is ButtonStyle.SUCCESS
    assert buttons["verify_admin:1:ban"].style is ButtonStyle.DANGER
    # 单选与任选其一模式的 custom_qa 无确认行
    single = _session_with(
        "custom_qa", {"question": "Q", "options": ["a", "b"], "answers": ["a"]}
    )
    single.id = 2
    single_markup = challenge._challenge_markup(single, "zh-CN")
    single_callbacks = [
        str(b.callback_data or "") for row in single_markup.inline_keyboard for b in row
    ]
    assert not any("submit" in c for c in single_callbacks)
    any_of = _session_with(
        "custom_qa",
        {
            "question": "Q",
            "options": ["a", "b"],
            "answers": ["a", "b"],
            "select": "any",
        },
    )
    any_of.id = 3
    any_markup = challenge._challenge_markup(any_of, "zh-CN")
    any_callbacks = [
        str(b.callback_data or "") for row in any_markup.inline_keyboard for b in row
    ]
    assert not any("submit" in c for c in any_callbacks)


def test_challenge_text_includes_timeout_hint():
    config = ChatConfig(verify_timeout_seconds=120, verify_max_attempts=3)
    text = challenge.build_challenge_text(
        config,
        "math_easy",
        {"a": 1, "b": 2, "answer": 3, "options": [1, 2, 3, 4]},
        3,
        wrong_prefix=False,
        lang="zh-CN",
    )
    hint = i18n.t("bot.msg.verify.timeout_hint", locale="zh-CN").format(timeout=120)
    assert hint in text


def test_qa_challenge_text_distinguishes_select_mode():
    """全选模式提示多选, 任选其一模式提示单选文案。"""
    config = ChatConfig(verify_timeout_seconds=120, verify_max_attempts=3)
    multi = {
        "question": "Q?",
        "options": ["a", "b"],
        "answers": ["a", "b"],
        "select": "all",
    }
    any_of = {
        "question": "Q?",
        "options": ["a", "b"],
        "answers": ["a", "b"],
        "select": "any",
    }
    multi_text = challenge.build_challenge_text(
        config, "custom_qa", multi, 3, wrong_prefix=False, lang="zh-CN"
    )
    any_text = challenge.build_challenge_text(
        config, "custom_qa", any_of, 3, wrong_prefix=False, lang="zh-CN"
    )
    assert (
        i18n.t("bot.msg.verify.challenge_qa_multi", locale="zh-CN").split("\n")[0]
        in multi_text
    )
    assert (
        i18n.t("bot.msg.verify.challenge_qa", locale="zh-CN").split("\n")[0] in any_text
    )
    assert "选出所有" in multi_text and "选出所有" not in any_text


def test_challenge_text_mentions_the_target_user():
    config = ChatConfig(verify_timeout_seconds=120, verify_max_attempts=3)
    mention = "<a href='tg://user?id=123'>User</a>"
    text = challenge.build_challenge_text(
        config,
        "math_easy",
        {"a": 1, "b": 2, "answer": 3, "options": [1, 2, 3, 4]},
        3,
        wrong_prefix=False,
        lang="zh-CN",
        user_mention=mention,
    )
    assert text.startswith(mention + "\n")
    # 不传 mention 时无首行
    plain = challenge.build_challenge_text(
        config,
        "math_easy",
        {"a": 1, "b": 2, "answer": 3, "options": [1, 2, 3, 4]},
        3,
        wrong_prefix=False,
        lang="zh-CN",
    )
    assert not plain.startswith(mention)


def test_restrict_permissions_skips_sticker_method():
    """贴纸验证不限制发言: 客户端把 send_messages 当总开关, 部分放行无效,
    只能靠超时兜底。其余方式仍是全静音。"""
    assert challenge.restrict_permissions("sticker") is None
    for method in ("math_easy", "emoji", "custom_qa"):
        permissions = challenge.restrict_permissions(method)
        assert permissions is not None
        rights = permissions.write()
        assert rights.send_messages is True  # 全静音
        assert rights.send_stickers is True


# ------------------------------------------------------------------ DAO


async def _make_session(
    chat_id: int = -100_910_001,
    user_id: int = 123_456,
    **overrides,
) -> VerificationSession:
    session_row = VerificationSession(
        chat_id=chat_id,
        user_id=user_id,
        method=overrides.get("method", "math_easy"),
        payload=overrides.get("payload", challenge.make_math_challenge()),
        challenge_message_id=overrides.get("challenge_message_id"),
        attempts_left=overrides.get("attempts_left", 3),
        expires_at=overrides.get(
            "expires_at", datetime.now(UTC) + timedelta(seconds=120)
        ),
    )
    if overrides.get("created_at") is not None:
        session_row.created_at = overrides["created_at"]
    return await database.create_verification_session(session_row)


@pytest.fixture
def no_result_ttl(monkeypatch):
    """结果提示自动删除立即生效, 避免真实 30s 任务残留到测试结束。"""
    monkeypatch.setattr(session, "RESULT_MESSAGE_TTL", 0)


async def test_session_dao_roundtrip():
    session_row = await _make_session()
    assert session_row.id is not None

    got = await database.get_verification_session(session_row.id)
    assert got is not None and got.user_id == 123_456

    got.attempts_left = 1
    got.payload = {"x": 1}
    got.challenge_message_id = 42
    await database.update_verification_session(got)

    again = await database.get_verification_session(session_row.id)
    assert again is not None
    assert again.attempts_left == 1
    assert again.payload == {"x": 1}
    assert again.challenge_message_id == 42

    await database.delete_verification_session(session_row.id)
    assert await database.get_verification_session(session_row.id) is None


async def test_delete_verification_sessions_for_user():
    first = await _make_session(user_id=123_456)
    second = await _make_session(user_id=123_457)
    other = await _make_session(user_id=654_321)

    await database.delete_verification_sessions_for_user(-100_910_001, 123_456)

    assert await database.get_verification_session(first.id) is None
    assert await database.get_verification_session(second.id) is not None
    assert await database.get_verification_session(other.id) is not None


async def test_verified_member_dao_roundtrip():
    assert await database.is_user_verified(-100_910_001, 123_456) is False
    await database.mark_user_verified(-100_910_001, 123_456)
    await database.mark_user_verified(-100_910_001, 123_456)  # 重复记录不炸
    assert await database.is_user_verified(-100_910_001, 123_456) is True
    assert await database.is_user_verified(-100_910_001, 654_321) is False


async def test_load_active_sessions_populates_registry():
    session_row = await _make_session()

    await session.load_active_sessions()

    hit = session._get_for(-100_910_001, 123_456)
    assert hit is not None and hit.id == session_row.id
    assert session._sessions[session_row.id].id == session_row.id


# ------------------------------------------------------------------ sweep


class _FakeClient:
    """记录 Telegram 调用; get_users 抛错让 mention 走退化路径。"""

    def __init__(self, history: list | None = None) -> None:
        self.calls: list[tuple] = []
        self.history = history or []

    async def search_messages(
        self,
        chat_id: int,
        from_user: int | None = None,
        min_date=None,
        max_date=None,
        **kwargs,
    ):
        """模拟服务器端过滤: 只返回目标用户且在窗口期内的消息。"""
        for message in self.history:
            if from_user is not None and message.from_user.id != from_user:
                continue
            if min_date is not None and message.date < min_date:
                continue
            if max_date is not None and message.date > max_date:
                continue
            yield message

    async def ban_chat_member(self, chat_id: int, user_id: int) -> None:
        self.calls.append(("ban", chat_id, user_id))

    async def unban_chat_member(self, chat_id: int, user_id: int) -> None:
        self.calls.append(("unban", chat_id, user_id))

    async def restrict_chat_member(
        self, chat_id: int, user_id: int, permissions
    ) -> None:
        self.calls.append(("restrict", chat_id, user_id, permissions))

    async def delete_messages(self, chat_id: int, message_ids) -> None:
        self.calls.append(("delete", chat_id, message_ids))

    async def edit_message_text(
        self, chat_id: int, message_id: int, text: str, reply_markup=None
    ) -> None:
        self.calls.append(("edit", chat_id, message_id, text))

    async def get_users(self, user_id: int):
        raise RPCError(f"user {user_id} not found")

    async def send_message(self, chat_id: int, text: str) -> SimpleNamespace:
        self.calls.append(("notify", chat_id, text))
        return SimpleNamespace(id=1000)


async def _enabled_chat(chat_id: int, *, fail_action: str = "kick") -> None:
    chat = await make_chat(chat_id, title="Verify Chat")
    config = await database.get_chat_config(chat)
    config.verify_enabled = True
    config.verify_fail_action = fail_action
    await database.update_chat_config(chat, config)


async def test_sweep_fails_expired_with_kick(monkeypatch, no_result_ttl):
    await _enabled_chat(-100_910_001, fail_action="kick")
    session_row = await _make_session(
        expires_at=datetime.now(UTC) - timedelta(seconds=10)
    )
    fake = _FakeClient()
    monkeypatch.setattr(session, "client", fake)

    await session.verify_sweep()

    actions = [call[0] for call in fake.calls]
    assert "ban" in actions and "unban" in actions
    assert await database.get_verification_session(session_row.id) is None
    assert session._sessions == {}
    assert session._by_user == {}


@pytest.mark.parametrize(
    ("fail_action", "expect_ban", "expect_restrict"),
    [("ban", True, False), ("unrestrict", False, True)],
)
async def test_sweep_fail_honors_fail_action(
    monkeypatch, no_result_ttl, fail_action, expect_ban, expect_restrict
):
    await _enabled_chat(-100_910_002, fail_action=fail_action)
    session_row = await _make_session(
        chat_id=-100_910_002,
        expires_at=datetime.now(UTC) - timedelta(seconds=10),
    )
    fake = _FakeClient()
    monkeypatch.setattr(session, "client", fake)

    await session.verify_sweep()

    actions = [call[0] for call in fake.calls]
    assert ("ban" in actions) is expect_ban
    assert "unban" not in actions
    assert ("restrict" in actions) is expect_restrict
    if expect_restrict:
        restrict_call = next(call for call in fake.calls if call[0] == "restrict")
        # 全放开: 无任何限制标记, 用户恢复为群默认权限
        for name in challenge.PERMISSION_FIELDS:
            assert bool(getattr(restrict_call[3], name)) is True
    assert await database.get_verification_session(session_row.id) is None
    assert session._sessions == {}


async def test_sweep_cancels_when_chat_disabled(monkeypatch):
    # 群存在但 verify_enabled 为默认 False
    await make_chat(-100_910_003, title="Disabled Chat")
    session_row = await _make_session(
        chat_id=-100_910_003,
        expires_at=datetime.now(UTC) + timedelta(seconds=120),
    )
    fake = _FakeClient()
    monkeypatch.setattr(session, "client", fake)

    await session.verify_sweep()

    actions = [call[0] for call in fake.calls]
    assert "restrict" in actions
    assert "ban" not in actions and "unban" not in actions
    assert await database.get_verification_session(session_row.id) is None
    assert session._sessions == {}


async def test_sweep_drops_orphan_sessions(monkeypatch):
    # 聊天不存在 -> 静默清理, 无任何 Telegram 调用
    session_row = await _make_session(
        chat_id=-100_999_999,
        expires_at=datetime.now(UTC) + timedelta(seconds=120),
    )
    fake = _FakeClient()
    monkeypatch.setattr(session, "client", fake)

    await session.verify_sweep()

    assert fake.calls == []
    assert await database.get_verification_session(session_row.id) is None
    assert session._sessions == {}


async def test_result_messages_are_auto_deleted(monkeypatch):
    """成功/封禁/失败通知在 TTL 后自动删除。"""
    from kmua import common

    session_row = await _make_session(challenge_message_id=42)
    fake = _FakeClient()
    monkeypatch.setattr(session, "client", fake)
    monkeypatch.setattr(session, "RESULT_MESSAGE_TTL", 0)
    spawned: list = []
    monkeypatch.setattr(
        common,
        "spawn",
        lambda coro, *, name=None: spawned.append(coro),
    )

    await session._succeed_session(session_row, "zh-CN")

    assert len(spawned) == 1
    await spawned[0]  # 立即执行延迟删除协程(TTL=0)
    assert ("delete", -100_910_001, 42) in fake.calls
    assert await database.get_verification_session(session_row.id) is None


async def test_sweep_fail_deletes_sticker_window_messages(monkeypatch, no_result_ttl):
    """贴纸验证失败: 删除用户从入群到失败期间发送的消息, 窗口外不动。"""
    await _enabled_chat(-100_910_006, fail_action="kick")
    now = datetime.now(UTC)
    session_row = await _make_session(
        chat_id=-100_910_006,
        method="sticker",
        expires_at=now - timedelta(seconds=10),
        created_at=now - timedelta(minutes=2),
    )
    other_user = SimpleNamespace(
        date=now - timedelta(seconds=10), id=99, from_user=SimpleNamespace(id=999)
    )
    in_window = SimpleNamespace(
        date=now - timedelta(seconds=20), id=101, from_user=SimpleNamespace(id=123_456)
    )
    out_of_window = SimpleNamespace(
        date=now - timedelta(hours=2), id=100, from_user=SimpleNamespace(id=123_456)
    )
    fake = _FakeClient(history=[other_user, in_window, out_of_window])
    monkeypatch.setattr(session, "client", fake)

    await session.verify_sweep()

    assert ("delete", -100_910_006, [101]) in fake.calls  # 只删窗口内本人消息
    assert ("ban", -100_910_006, 123_456) in fake.calls  # kick 兜底照常
    assert ("unban", -100_910_006, 123_456) in fake.calls
    assert await database.get_verification_session(session_row.id) is None


# ------------------------------------------------------------------ 审查回归


def test_restore_permissions_roundtrip_and_fallback():
    """权限捕获 -> 序列化 -> 恢复往返; 缺失/脏数据回退到全放开。"""
    original = challenge._unrestricted_permissions()
    original.can_send_messages = False
    original.can_invite_users = False
    restored = challenge.deserialize_permissions(
        challenge.serialize_permissions(original)
    )
    for name in challenge.PERMISSION_FIELDS:
        assert bool(getattr(restored, name)) is bool(getattr(original, name))

    fallback = challenge.deserialize_permissions(None)
    for name in challenge.PERMISSION_FIELDS:
        assert bool(getattr(fallback, name)) is True  # 全放开, 无任何限制标记

    dirty = challenge.deserialize_permissions({"can_send_messages": True})
    assert dirty.can_send_messages is True
    assert dirty.can_change_info is True  # 缺失字段回退到全放开


def test_restore_permissions_for_session():
    """贴纸会话不改权限; 其他会话按 payload 存储的权限恢复。"""
    sticker = VerificationSession(chat_id=1, user_id=2, method="sticker", payload={})
    assert challenge.restore_permissions_for_session(sticker) is None

    perms = challenge._unrestricted_permissions()
    payload = {
        challenge.RESTORE_PERMISSIONS_KEY: challenge.serialize_permissions(perms)
    }
    row = VerificationSession(chat_id=1, user_id=2, method="math_easy", payload=payload)
    assert challenge.restore_permissions_for_session(row).can_send_messages is True


def test_restore_permissions_for_session_lifts_when_nothing_captured():
    """普通成员入群验证(payload 无权限记录): 恢复为全放开, 不留限制记录。"""
    row = VerificationSession(
        chat_id=1, user_id=2, method="math_easy", payload={"a": 1}
    )
    restored = challenge.restore_permissions_for_session(row)
    assert restored is not None
    for name in challenge.PERMISSION_FIELDS:
        assert bool(getattr(restored, name)) is True
    rights = restored.write()
    assert rights.send_messages is False
    assert rights.change_info is False
    assert rights.invite_users is False
    assert rights.pin_messages is False
    assert rights.manage_topics is False
    assert rights.edit_rank is False


def test_restore_permissions_for_session_preserves_custom_restrictions():
    """管理员禁言等自定义限制原样恢复, 不被全放开覆盖。"""
    muted = {name: True for name in challenge.PERMISSION_FIELDS}
    muted["can_send_messages"] = False
    payload = {challenge.RESTORE_PERMISSIONS_KEY: muted}
    row = VerificationSession(chat_id=1, user_id=2, method="math_easy", payload=payload)
    restored = challenge.restore_permissions_for_session(row)
    assert restored.can_send_messages is False
    assert restored.can_change_info is True


async def test_verify_target_resolves_channel_senders():
    """回复频道消息时目标取频道实体, 不落到命令发送者。"""
    from pyrogram.enums import ChatType
    from pyrogram.types import User

    from kmua import enums
    from kmua.plugins.verify import verify as verify_mod

    sender = User(id=123, first_name="Admin", is_bot=False)
    plain_reply = SimpleNamespace(
        from_user=User(id=456, first_name="U", is_bot=False), sender_chat=None
    )
    msg = SimpleNamespace(
        reply_to_message=plain_reply, command=None, from_user=sender, sender_chat=None
    )
    target = await verify_mod._test_verify_target(SimpleNamespace(), msg)
    assert target is not None and target.id == 456

    channel = SimpleNamespace(id=-100_123, type=ChatType.CHANNEL)
    channel_reply = SimpleNamespace(from_user=None, sender_chat=channel)
    msg = SimpleNamespace(
        reply_to_message=channel_reply, command=None, from_user=sender, sender_chat=None
    )
    target = await verify_mod._test_verify_target(SimpleNamespace(), msg)
    assert target is channel

    # 匿名管理员发言(sender_chat 是群自身)不算频道, 落到命令发送者
    group_as_chat = SimpleNamespace(id=-100_999, type=ChatType.SUPERGROUP)
    anon_reply = SimpleNamespace(from_user=None, sender_chat=group_as_chat)
    msg = SimpleNamespace(
        reply_to_message=anon_reply, command=None, from_user=sender, sender_chat=None
    )
    target = await verify_mod._test_verify_target(SimpleNamespace(), msg)
    assert target is sender

    # from_user 是匿名管理员 id 时同样跳过, 频道仍可作目标
    anon_user = SimpleNamespace(id=enums.ChatID.ANONYMOUS_ADMIN)
    msg = SimpleNamespace(
        reply_to_message=SimpleNamespace(from_user=anon_user, sender_chat=channel),
        command=None,
        from_user=sender,
        sender_chat=None,
    )
    target = await verify_mod._test_verify_target(SimpleNamespace(), msg)
    assert target is channel

    # 无回复无参数: 命令发送者
    msg = SimpleNamespace(
        reply_to_message=None, command=None, from_user=sender, sender_chat=None
    )
    target = await verify_mod._test_verify_target(SimpleNamespace(), msg)
    assert target is sender


async def test_verify_command_replies_when_start_fails(monkeypatch):
    """/testverify 启动失败(如无法限制目标)时回复提示, 不再静默。"""
    from kmua.plugins.verify import verify as verify_mod

    replies: list[str] = []

    class _Msg:
        chat = SimpleNamespace(id=-100_910_001)
        from_user = SimpleNamespace(id=777)
        sender_chat = None
        reply_to_message = None
        command = ["testverify"]

        async def reply_text(self, text, **kwargs):
            replies.append(text)

    async def fake_config(chat_id):
        cfg = ChatConfig()
        cfg.verify_enabled = True
        return cfg

    async def fake_start(client, chat_id, user, config):
        return False

    async def fake_admin(user_id):
        return SimpleNamespace(is_bot_global_admin=True)

    monkeypatch.setattr(verify_mod, "_chat_config", fake_config)
    monkeypatch.setattr(verify_mod, "_start_verification", fake_start)
    monkeypatch.setattr(verify_mod.database, "get_user_by_id", fake_admin)
    monkeypatch.setattr(verify_mod, "_get_for", lambda chat_id, user_id: None)

    await verify_mod.test_verify_command(SimpleNamespace(), _Msg())

    assert replies == [i18n.t("bot.msg.verify.test_verify_failed", locale="zh-CN")]


def test_verify_context_is_bot_handles_chat_targets():
    """频道(无 is_bot 属性)目标不触发 AttributeError。"""
    from pyrogram.types import User

    user_ctx = challenge.VerifyContext(
        chat_id=1, user=User(id=1, first_name="T", is_bot=True), is_join=True
    )
    assert user_ctx.is_bot is True
    chat_ctx = challenge.VerifyContext(
        chat_id=1, user=SimpleNamespace(id=-100), is_join=True
    )
    assert chat_ctx.is_bot is False


async def test_user_mention_channel_fallback():
    """频道目标(不在用户库)退化为 id 链接, 不抛异常。"""
    from pyrogram.enums import ChatType

    channel = SimpleNamespace(id=-100_123, type=ChatType.CHANNEL)
    mention = await session._user_mention(channel)
    assert mention == "<a href='tg://user?id=-100123'>User</a>"


async def test_capture_restore_permissions_member_specific_only():
    """只捕获成员已有自定义限制; 普通成员返回 None, 读取失败也返回 None。"""

    class _FakeClient:
        def __init__(self, member):
            self.member = member

        async def get_chat_member(self, chat_id, user_id):
            return self.member

    plain = SimpleNamespace(permissions=None)
    assert (
        await session.capture_restore_permissions(_FakeClient(plain), -100, 1) is None
    )

    restricted = SimpleNamespace(permissions=challenge._unrestricted_permissions())
    captured = await session.capture_restore_permissions(
        _FakeClient(restricted), -100, 1
    )
    assert captured is restricted.permissions

    class _RaisingClient:
        async def get_chat_member(self, chat_id, user_id):
            raise ValueError("boom")

    assert (
        await session.capture_restore_permissions(_RaisingClient(), -100, 1) is None
    )


def test_challenge_markup_two_options_no_empty_rows():
    """两选项题目不生成空键盘行。"""
    payload = {
        "question": "Q?",
        "options": ["a", "b"],
        "answers": ["a"],
        "select": "all",
    }
    row = VerificationSession(chat_id=1, user_id=2, method="custom_qa", payload=payload)
    markup = challenge._challenge_markup(row, "zh-CN")
    assert all(len(r) > 0 for r in markup.inline_keyboard)
    assert len(markup.inline_keyboard) == 2  # 作答行 + 管理员行


async def test_sweep_disabled_chat_wins_over_expired(monkeypatch):
    """停用群优先于过期: 只恢复权限取消, 不执行失败动作。"""
    await make_chat(-100_910_004, title="Disabled Expired")
    session_row = await _make_session(
        chat_id=-100_910_004,
        expires_at=datetime.now(UTC) - timedelta(seconds=10),
    )
    fake = _FakeClient()
    monkeypatch.setattr(session, "client", fake)

    await session.verify_sweep()

    actions = [call[0] for call in fake.calls]
    assert "restrict" in actions
    assert "ban" not in actions and "unban" not in actions
    assert await database.get_verification_session(session_row.id) is None
    assert session._sessions == {}


async def _verify_module_harness(monkeypatch, *, enabled: bool = True):
    """maybe_verify 测试脚手架: 可控配置 + 记录启动的 stub。"""
    from kmua.plugins.verify import verify as verify_mod

    started: list[int] = []

    async def fake_start(client, chat_id, user, config, chat=None):
        started.append(chat_id)
        await asyncio.sleep(0.05)  # 放大并发竞争窗口
        session._sessions[999] = SimpleNamespace(id=999)
        session._by_user[(chat_id, user.id)] = 999
        return True

    async def fake_config(chat_id):
        cfg = ChatConfig()
        cfg.verify_enabled = enabled
        cfg.verify_strategy = "first_message"
        return cfg

    monkeypatch.setattr(verify_mod, "_chat_config", fake_config)
    monkeypatch.setattr(verify_mod, "_start_verification", fake_start)

    async def fake_verified(*args, **kwargs):
        return False

    monkeypatch.setattr(verify_mod.database, "is_user_verified", fake_verified)
    return verify_mod, started


async def test_maybe_verify_returns_intercept_and_serializes(monkeypatch):
    """未验证且无会话 -> 创建并拦截; 已有会话 -> 拦截但不重复创建; 未启用 -> 放行。"""
    verify_mod, started = await _verify_module_harness(monkeypatch)
    ctx = _verify_ctx(is_join=False)

    assert await verify_mod.maybe_verify(SimpleNamespace(), ctx) is True
    assert started == [ctx.chat_id]

    assert await verify_mod.maybe_verify(SimpleNamespace(), ctx) is True
    assert started == [ctx.chat_id]  # 不重复创建

    disabled_mod, _ = await _verify_module_harness(monkeypatch, enabled=False)
    assert await disabled_mod.maybe_verify(SimpleNamespace(), ctx) is False


async def test_maybe_verify_concurrent_messages_create_one_session(monkeypatch):
    """并发首条消息只创建一个验证会话(每用户锁串行化)。"""
    verify_mod, started = await _verify_module_harness(monkeypatch)
    ctx = _verify_ctx(is_join=False)

    results = await asyncio.gather(
        verify_mod.maybe_verify(SimpleNamespace(), ctx),
        verify_mod.maybe_verify(SimpleNamespace(), ctx),
    )

    assert started == [ctx.chat_id]  # 只创建一次
    assert results == [True, True]
