"""每次 agent 调用的额度, 按 token 用量计费。

扣费顺序固定: 发言者免费额度 → 群免费额度 → 发言者余额 → 群余额。

**时机**: token 用量只有 run 跑完才知道, 所以入口只做预检 (`can_start`: 任一位付款方还有
额度就放行), 扣减发生在 run 成功后 (`settle`: 按实际用量依次扣)。一次 run 因此可能花掉超过
剩余额度的量 —— 超出部分如实记账, 余额扣成负数(欠费), 下一次调用的预检就会拒绝, 直到运维补发。
代价是"预检通过"不再保证"付得起"; 收益是计量单位与真实成本一致。

账户只有一个身份概念 —— 说话的那个人, 和所在的会话。匿名管理与频道身份两者都没有自己的
账户(`sender_chat` 是频道或者就是本群), 于是它们只能花群账户的额度 —— 群没被分配额度就拒绝,
这是可控的: 运维在面板给这个群配额度池、余额, 或直接标记豁免。

只覆盖对话 agent(用户触发的 wake / ask 回调 / follow-up); bot 自己跑起来的辅助 agent 没有
可计费的发言人, 不在额度内。
"""

from __future__ import annotations

from dataclasses import dataclass

import pyrogram
import pyrogram.enums
import pyrogram.types
from pydantic_ai.usage import RunUsage

from kmua import database
from kmua.common.memory_store import memttlcache
from kmua.config import app_config
from kmua.enums import ChatID
from kmua.i18n import i18n
from kmua.logger import logger
from kmua.plugins.agent import state as agent_state

SCOPE_USER = database.SCOPE_USER
SCOPE_CHAT = database.SCOPE_CHAT

# 匿名管理/服务账号没有自己的账户; 它们的消息只记在群账上。
# 见 kmua/enums.py::ChatID。
PSEUDO_USER_IDS = frozenset(
    (int(ChatID.ANONYMOUS_ADMIN), int(ChatID.SERVICE_CHAT), int(ChatID.FAKE_CHANNEL))
)

# 群聊里额度用尽提示的最小间隔, 免得被刷屏; 也是"已用尽"标记的存活时间。
_NOTICE_TTL_SECONDS = 60


@dataclass(frozen=True)
class Subject:
    """一次调用的付款账户组合。

    `user_id` 为 None 表示说话的人没有自己的账户(匿名管理、频道身份、服务账号);
    `chat_id` 在私聊里就是用户本人, 所以 `accounts()` 不会为它单开一个账户。
    """

    user_id: int | None
    chat_id: int | None
    in_group: bool

    def accounts(self) -> list[tuple[str, int]]:
        """按扣费顺序排列的账户: 先发言者, 后所在群。"""
        accounts: list[tuple[str, int]] = []
        if self.user_id is not None:
            accounts.append((SCOPE_USER, self.user_id))
        if self.in_group and self.chat_id is not None:
            accounts.append((SCOPE_CHAT, self.chat_id))
        return accounts

    @property
    def cache_key(self) -> str:
        """用尽标记与提示节流用的稳定键。"""
        return f"{self.chat_id or 0}:{self.user_id or 0}"


@dataclass(frozen=True)
class AccountState:
    """一个账户的只读快照, token 单位。"""

    scope: str
    scope_id: int
    requests_today: int
    free_used_tokens: int
    free_limit_tokens: int | None
    credits: int
    input_tokens_today: int
    output_tokens_today: int

    @property
    def free_left(self) -> int | None:
        if self.free_limit_tokens is None:
            return None
        return max(0, self.free_limit_tokens - self.free_used_tokens)

    @property
    def exhausted(self) -> bool:
        """欠费的余额(`credits <= 0`)与用完的免费额度都意味着下一次会被拒绝。"""
        return self.free_left == 0 and self.credits <= 0


@dataclass(frozen=True)
class QuotaState:
    """一次调用的额度快照; 账户顺序与 `Subject.accounts()` 一致。"""

    accounts: list[AccountState]
    exempt: bool

    @property
    def user(self) -> AccountState | None:
        return next((a for a in self.accounts if a.scope == SCOPE_USER), None)

    @property
    def chat(self) -> AccountState | None:
        return next((a for a in self.accounts if a.scope == SCOPE_CHAT), None)

    @property
    def exhausted(self) -> bool:
        return not self.exempt and (
            not self.accounts or all(a.exhausted for a in self.accounts)
        )


def subject_for_chat(user_id: int | None, chat: pyrogram.types.Chat | None) -> Subject:
    """从(发言者 id, 会话)构造: 调用方已经知道发言者是谁时用这个。"""
    if chat is None or chat.id is None:
        return Subject(user_id=user_id, chat_id=None, in_group=False)
    in_group = chat.type not in (
        pyrogram.enums.ChatType.PRIVATE,
        pyrogram.enums.ChatType.BOT,
    )
    return Subject(user_id=user_id, chat_id=chat.id, in_group=in_group)


def subject_of(message: pyrogram.types.Message) -> Subject:
    """从消息推导付款账户。

    发言者口径跟 `middlewares/before.py` 一致: `sender_chat` 优先 —— 匿名管理与频道
    消息都走这里, 它们没有个人账户, 于是只记群账。
    """
    chat = message.chat
    user_id: int | None = None
    if message.sender_chat is None and message.from_user is not None:
        candidate = message.from_user.id
        if candidate not in PSEUDO_USER_IDS:
            user_id = candidate
    return subject_for_chat(user_id, chat)


async def _plan(subject: Subject) -> tuple[list[database.ChargeAccount], bool]:
    """本次调用的付款账户(含各自免费上限, token)与是否豁免。"""
    exempt = False
    accounts: list[database.ChargeAccount] = []
    if subject.user_id is not None:
        if subject.user_id in app_config.owners:
            exempt = True
        else:
            user = await database.get_user_by_id(subject.user_id)
            exempt = user is not None and user.is_bot_global_admin
        limit = app_config.agent_quota_free_daily_tokens
        accounts.append(
            database.ChargeAccount(
                SCOPE_USER, subject.user_id, None if limit <= 0 else limit
            )
        )
    if subject.in_group and subject.chat_id is not None:
        policy = await database.get_chat_policy(subject.chat_id)
        exempt = exempt or policy.agent_quota_exempt
        accounts.append(
            database.ChargeAccount(
                SCOPE_CHAT, subject.chat_id, policy.agent_quota_daily_tokens
            )
        )
    return accounts, exempt


async def get_state(subject: Subject) -> QuotaState:
    """完整只读状态(每个账户的用量/额度/余额 + 豁免), 供 /quota 与拒绝提示使用。"""
    accounts, exempt = await _plan(subject)
    day = database.utc_day()
    states: list[AccountState] = []
    for account in accounts:
        requests, free_used, input_tokens, output_tokens = await database.get_usage(
            account.scope, account.scope_id, day
        )
        states.append(
            AccountState(
                scope=account.scope,
                scope_id=account.scope_id,
                requests_today=requests,
                free_used_tokens=free_used,
                free_limit_tokens=account.free_limit,
                credits=await database.get_credit(account.scope, account.scope_id),
                input_tokens_today=input_tokens,
                output_tokens_today=output_tokens,
            )
        )
    return QuotaState(accounts=states, exempt=exempt)


async def can_start(subject: Subject) -> bool:
    """入口预检: 任一位付款方还有免费额度或正余额就放行。

    不扣任何东西 —— 这一次会花多少要等跑完才知道。所以预检只回答"还付得起吗",
    真正的把关在下一次: 一旦这次把额度花光(甚至花成欠费), 预检就会开始拒绝。

    每次都查库而不是缓存"已用尽": 缓存的拒绝会在运维补发额度后继续挡住用户最多一个
    TTL, 而这里省下的只是每账户一次点查 —— 相对 agent 随后要做的取历史、下载媒体、
    调模型, 不值一提。刷屏防护由 `notify_exhausted` 的提示节流负责, 它不会掩盖状态。
    """
    accounts, exempt = await _plan(subject)
    return exempt or await _has_capacity(accounts)


async def _has_capacity(accounts: list[database.ChargeAccount]) -> bool:
    day = database.utc_day()
    for account in accounts:
        if account.free_limit is None:
            # 该账户的免费部分不限额(agent_quota_free_daily_tokens = 0)
            return True
        _, free_used, _, _ = await database.get_usage(
            account.scope, account.scope_id, day
        )
        if free_used < account.free_limit:
            return True
        if await database.get_credit(account.scope, account.scope_id) > 0:
            return True
    return False


async def settle(subject: Subject, usage: RunUsage | None) -> None:
    """按本次 run 的实际 token 用量结算。

    用量记到本次调用涉及的每个账户上(含被群池或别人的余额付款的那一次), 面板因此
    能看到群的真实消耗; 扣减则由 `database.charge_tokens` 按固定顺序完成, 且与记账
    同属一个事务。
    豁免的账户不计数也不扣费 —— 这正是"豁免"的含义。
    """
    accounts, exempt = await _plan(subject)
    if exempt:
        return
    day = database.utc_day()
    input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
    output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
    await database.record_and_charge(
        subject.accounts(), accounts, day, input_tokens, output_tokens
    )


def _notice_key(subject: Subject) -> str:
    return agent_state.quota_notice_key(subject.cache_key)


async def notify_exhausted(
    message: pyrogram.types.Message, subject: Subject, state: QuotaState, lang: str
) -> None:
    """告诉用户额度用完了。群聊里同一账号 60 秒最多一条, 私聊每次都提示。"""
    if subject.in_group:
        key = _notice_key(subject)
        if await memttlcache.get(key):
            return
        await memttlcache.set(key, True, ttl=_NOTICE_TTL_SECONDS)
    try:
        await message.reply_text(exhausted_text(state, lang))
    except Exception as e:
        logger.warning(f"Failed to send quota notice: {e.__class__.__name__} - {e}")


_TOKEN_UNITS: tuple[tuple[int, str], ...] = (
    (1_000, "k"),
    (1_000_000, "M"),
    (1_000_000_000, "B"),
    (1_000_000_000_000, "T"),
)


def fmt_tokens(value: int) -> str:
    """把 token 数压成人类可读的短形式; 面板和 bot 文案共用同一套口径。

    取整到一位小数后再定单位, 所以临界值会进位到更大的单位。不到一千的数字原样
    显示, 小额额度才看得出自己到底是多少。
    """
    if abs(value) < _TOKEN_UNITS[0][0]:
        return str(value)
    scale, suffix = _TOKEN_UNITS[-1]
    for candidate, candidate_suffix in _TOKEN_UNITS:
        if abs(float(f"{value / candidate:.1f}")) < 1_000:
            scale, suffix = candidate, candidate_suffix
            break
    return f"{value / scale:.1f}{suffix}"


def exhausted_text(state: QuotaState, lang: str) -> str:
    """额度用尽的提示语: 文案按是否有个人账户二选一。"""
    user = state.user
    if user is None or user.free_limit_tokens is None:
        return i18n.t("bot.msg.agent.quota.exhausted_group", locale=lang)
    return i18n.t("bot.msg.agent.quota.exhausted", locale=lang)


def status_text(state: QuotaState, lang: str) -> str:
    """/quota 的输出: 个人账户必有, 群账户只在群里有额度时列出。

    不限额也要列出群账户: 群里的用户只能从这里看到本群还剩多少。
    """
    lines: list[str] = []
    user = state.user
    if user is not None:
        used_total = user.input_tokens_today + user.output_tokens_today
        if user.free_limit_tokens is None:
            lines.append(
                i18n.t("bot.msg.agent.quota.status_unlimited", locale=lang).format(
                    used=user.requests_today, tokens=fmt_tokens(used_total)
                )
            )
        else:
            lines.append(
                i18n.t("bot.msg.agent.quota.calls_today", locale=lang).format(
                    used=user.requests_today, tokens=fmt_tokens(used_total)
                )
            )
            lines.append(
                i18n.t("bot.msg.agent.quota.free_line", locale=lang).format(
                    used=fmt_tokens(user.free_used_tokens),
                    limit=fmt_tokens(user.free_limit_tokens),
                )
            )
            lines.append(
                i18n.t("bot.msg.agent.quota.credits_line", locale=lang).format(
                    credits=fmt_tokens(user.credits)
                )
            )
    chat = state.chat
    if chat is not None and (chat.free_limit_tokens or chat.credits):
        lines.append(
            i18n.t("bot.msg.agent.quota.chat_line", locale=lang).format(
                used=fmt_tokens(chat.free_used_tokens),
                limit=fmt_tokens(chat.free_limit_tokens or 0),
                credits=fmt_tokens(chat.credits),
            )
        )
    if not lines:
        # 没有个人账户(匿名管理)且群里也没额度时, 总得说点什么。
        return i18n.t("bot.msg.agent.quota.status_none", locale=lang)
    return "\n".join(lines)


__all__ = [
    "PSEUDO_USER_IDS",
    "AccountState",
    "QuotaState",
    "Subject",
    "can_start",
    "exhausted_text",
    "fmt_tokens",
    "get_state",
    "notify_exhausted",
    "settle",
    "status_text",
    "subject_for_chat",
    "subject_of",
]
