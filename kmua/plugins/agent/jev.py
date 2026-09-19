"""Experimental: jev (TypeSafe System One) decisions for the follow-up check.

jev is not a chat model: it takes a ``state`` plus typed ``questions`` and
returns typed answers (yes/no probability / choice / score), never text. It
therefore has no pydantic-ai model class; this module speaks the System One
HTTP API directly.

Only the follow-up relevance check needs this path. Removing the feature means
deleting this module, the branch in :mod:`kmua.plugins.agent.followup`, the
``agent_followup_jev_model`` config field and its entry in
:mod:`kmua.webapp.sanitize`.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx
from pydantic import BaseModel
from pydantic_ai.usage import RunUsage

from kmua.common.http import get_agent_http_client
from kmua.plugins.agent import provider

_URL_PATH = "/systemone"
# jev returns calibrated probabilities; at/above this one the new message is
# treated as continuing the previous topic.
_RELEVANCE_THRESHOLD = 0.5

_RELEVANCE_QUESTION = {
    "type": "noul",
    "instructions": "新消息是否是对 Bot 回复的评论、疑问、补充、反驳或相关讨论?",
    "criteria": {
        "true": "新消息与 Bot 回复的话题存在明显关联",
        "false": "新消息与 Bot 回复的话题无关, 或无法确定是否相关",
    },
}


class JevRelevanceOutput(BaseModel):
    """Same shape as the small model's ``RelevanceCheck`` output."""

    relevance: bool
    reason: str


@dataclass(frozen=True)
class JevRelevanceResult:
    """Minimal stand-in for an ``AgentRunResult``: ``output`` + ``usage``."""

    output: JevRelevanceOutput
    usage: RunUsage


class _Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0


class _Answer(BaseModel):
    type: str
    noul: float | None = None


class _Response(BaseModel):
    answers: dict[str, _Answer]
    usage: _Usage | None = None


async def check_relevance(
    state: str,
    *,
    spec: str,
    timeout: float | None = None,
) -> JevRelevanceResult:
    """Ask jev whether *state*'s new message continues the previous topic.

    *spec* is a ``provider/model`` spec; the provider's ``url`` must be the
    System One base URL (``https://api.typesafe.ai/v1``) and the model is a
    TypeSafe model name such as ``jev-latest``.
    """
    cfg, model_name = provider.resolve_spec(spec)
    url = f"{cfg.url.rstrip('/')}{_URL_PATH}"
    headers = {"Authorization": f"Bearer {cfg.key}"}
    payload = {
        "model": model_name,
        "state": state,
        "questions": {"relevance": _RELEVANCE_QUESTION},
    }

    # Reuse the cached proxied client when a proxy is configured; otherwise the
    # check owns a short-lived client (at most one request per check).
    client = get_agent_http_client(cfg.proxy)
    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient()
    try:
        response = await client.post(
            url, json=payload, headers=headers, timeout=timeout
        )
    finally:
        if owns_client:
            await client.aclose()

    if response.status_code >= 400:
        raise RuntimeError(
            f"jev request failed: HTTP {response.status_code} {response.text[:200]}"
        )
    data = _Response.model_validate(response.json())
    answer = data.answers.get("relevance")
    if answer is None or answer.noul is None:
        raise RuntimeError(
            f"jev response carried no probability: {response.text[:200]}"
        )

    usage = RunUsage(
        requests=1,
        input_tokens=data.usage.input_tokens if data.usage else 0,
        output_tokens=data.usage.output_tokens if data.usage else 0,
    )
    return JevRelevanceResult(
        output=JevRelevanceOutput(
            relevance=answer.noul >= _RELEVANCE_THRESHOLD,
            reason=f"jev probability={answer.noul:.3f}",
        ),
        usage=usage,
    )
