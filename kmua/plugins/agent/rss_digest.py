"""RSS × Agent: digest summaries and chat broadcasts for pushed feed entries.

Independent of the main agent: importing this module must never build the
chat agent (``kmua.plugins.agent.agent``), so the RSS poll job can use it even
when the chat agent is disabled. Both entry points are gated on
``app_config.agent and app_config.agent_model``; when the gate fails they
return the "no agent output" values (``{}`` / ``None``) and the caller falls
back to the raw rendered entry.
"""

import asyncio
import json
from typing import Any

from pydantic import BaseModel, Field
from pydantic_ai import Agent, PromptedOutput

from kmua.config import app_config
from kmua.logger import logger
from kmua.plugins.agent import provider
from kmua.services.rss import FeedEntry

_DIGEST_TIMEOUT = 30.0
"""Hard timeout in seconds for one LLM call; the poll job must never stall."""


class RssEntrySummary(BaseModel):
    """One entry's chat-flavored take, keyed by the entry's stable id."""

    entry_id: str = Field(description="条目 ID, 必须是输入中给出的 [entry_id]")
    summary: str = Field(description="该条目的 1-2 句群聊口吻点评, 指出它为什么值得看")


class RssDigestSummaries(BaseModel):
    """Digest of a push batch: per-entry takes for the entries worth mentioning."""

    summaries: list[RssEntrySummary] = Field(description="值得点评的条目列表")


_digest_agent: Agent[Any, RssDigestSummaries] | None = None
_broadcast_agent: Agent[Any, str] | None = None


def _make_digest_agent() -> Agent[Any, RssDigestSummaries]:
    assert app_config.agent_model is not None, "agent_model must be set"
    return Agent(
        model=provider.make_chat_model(app_config.agent_model),
        # PromptedOutput: the model returns the JSON as text, which pydantic-ai
        # parses afterwards. Native output forces tool_choice, which some
        # providers reject (DeepSeek with thinking enabled -> HTTP 400).
        output_type=PromptedOutput(
            RssDigestSummaries,
            description="返回条目点评列表: summaries 为数组, 每项含 entry_id 与 summary",
        ),
        retries=2,
    )


def _make_broadcast_agent() -> Agent[Any, str]:
    assert app_config.agent_model is not None, "agent_model must be set"
    return Agent(
        model=provider.make_chat_model(app_config.agent_model),
        output_type=str,
        retries=2,
    )


def build_digest_prompt(
    entries: list[FeedEntry], feed_title: str, lang: str = "zh-CN"
) -> str:
    """Build the prompt for per-entry summaries of one push batch.

    Pure function; the digest agent turns this into ``RssDigestSummaries``.
    ``lang`` is the chat's delivery locale (e.g. ``zh-CN``), so the take is
    written in the language the subscribers actually read.
    """
    lines = [
        f"以下是从 RSS feed「{feed_title}」抓取到的一批新条目, 需要你为其中部分条目写群聊口吻的点评:"
    ]
    for entry in entries:
        summary = entry.summary[:300].replace("\n", " ")
        lines.append(f"\n[{entry.entry_id}]")
        lines.append(f"标题: {entry.title}")
        lines.append(f"链接: {entry.link}")
        if summary:
            lines.append(f"内容摘要: {summary}")
    lines.append(
        f"\n要求: 对每条值得群友关注的条目输出 1-2 句点评, 指出它为什么值得看; "
        f"不值得提的条目可以省略。点评用 {lang} 语言, 口语化, 不要复述原文。"
    )
    lines.append(
        "\n输出格式: 一个 JSON 对象, summaries 为数组, 每项为 "
        '{"entry_id": "<条目ID>", "summary": "<点评>"}。只输出 JSON, 不要输出其它内容。'
    )
    return "\n".join(lines)


def _summaries_list(raw: Any) -> list[Any]:
    """Extract the summary item list from a parsed JSON value."""
    if not isinstance(raw, dict):
        return []
    data = raw.get("summaries")
    return data if isinstance(data, list) else []


def parse_digest_output(
    raw: RssDigestSummaries | str | dict, valid_ids: set[str]
) -> dict[str, str]:
    """Parse the digest agent's output into an entry_id -> summary map.

    Accepts a ``RssDigestSummaries`` instance, JSON text (``{"summaries":
    [{entry_id, summary}, ...]}``) or a plain dict. Anything that does not
    parse, and any entry_id outside ``valid_ids``, is dropped.
    """
    if isinstance(raw, RssDigestSummaries):
        items = raw.summaries
    elif isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return {}
        items = _summaries_list(raw)
    elif isinstance(raw, dict):
        items = _summaries_list(raw)
    else:
        return {}
    out: dict[str, str] = {}
    for item in items:
        if isinstance(item, dict):
            entry_id = str(item.get("entry_id", ""))
            summary = item.get("summary", "")
        elif isinstance(item, RssEntrySummary):
            entry_id = item.entry_id
            summary = item.summary
        else:
            continue
        if entry_id in valid_ids and isinstance(summary, str) and summary.strip():
            out[entry_id] = summary
    return out


def build_broadcast_prompt(
    entries: list[FeedEntry], feed_title: str, lang: str = "zh-CN"
) -> str:
    """Build the prompt for one chat broadcast covering the whole batch.

    Pure function; the broadcast agent returns plain text. ``lang`` is the
    chat's delivery locale, so the message is written in the group's language.
    """
    lines = [f"以下是从 RSS feed「{feed_title}」抓取到的新条目:"]
    for entry in entries:
        summary = entry.summary[:300].replace("\n", " ")
        lines.append(f"\n- 标题: {entry.title}")
        lines.append(f"  链接: {entry.link}")
        if summary:
            lines.append(f"  内容摘要: {summary}")
    lines.append(
        f"\n你是一个群聊成员, 刚看到这些新内容。请发一条 1-3 句的群聊消息讨论它们: "
        f"整体点评这一批内容(不要逐条罗列), 至少包含一个条目的标题和链接, "
        f"用 {lang} 语言, 口语化, 不用列表符号。"
    )
    return "\n".join(lines)


async def generate_rss_digest(
    entries: list[FeedEntry], feed_title: str, lang: str = "zh-CN"
) -> dict[str, str]:
    """Summarize one push batch; {} means "no agent output, use raw push"."""
    global _digest_agent
    if not entries or not (app_config.agent and app_config.agent_model):
        return {}
    try:
        if _digest_agent is None:
            _digest_agent = _make_digest_agent()
        result = await asyncio.wait_for(
            _digest_agent.run(
                user_prompt=build_digest_prompt(entries, feed_title, lang),
            ),
            timeout=_DIGEST_TIMEOUT,
        )
        return parse_digest_output(result.output, {e.entry_id for e in entries})
    except Exception as e:
        logger.warning(
            f"rss_digest: summary generation failed for {feed_title!r}: "
            f"{e.__class__.__name__}: {e}"
        )
        return {}


async def generate_rss_broadcast(
    entries: list[FeedEntry], feed_title: str, lang: str = "zh-CN"
) -> str | None:
    """Write one broadcast message for the batch; None means "skip broadcast"."""
    global _broadcast_agent
    if not entries or not (app_config.agent and app_config.agent_model):
        return None
    try:
        if _broadcast_agent is None:
            _broadcast_agent = _make_broadcast_agent()
        result = await asyncio.wait_for(
            _broadcast_agent.run(
                user_prompt=build_broadcast_prompt(entries, feed_title, lang),
            ),
            timeout=_DIGEST_TIMEOUT,
        )
        text = (result.output or "").strip()
        return text or None
    except Exception as e:
        logger.warning(
            f"rss_digest: broadcast generation failed for {feed_title!r}: "
            f"{e.__class__.__name__}: {e}"
        )
        return None


__all__ = [
    "RssDigestSummaries",
    "build_broadcast_prompt",
    "build_digest_prompt",
    "generate_rss_broadcast",
    "generate_rss_digest",
    "parse_digest_output",
]
