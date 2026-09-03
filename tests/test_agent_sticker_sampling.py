"""Sticker-memory dynamic sampling: warmup ramp over the chat's stored count."""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import pyrogram.types
import pytest
from pydantic_ai import RunContext, RunUsage
from pydantic_ai.models.test import TestModel
from pydantic_ai.tools import ToolDefinition
from pyrogram.client import Client as PyrogramClient

from kmua.config import app_config
from kmua.plugins.agent import datatype, sticker_memory, sticker_vec


def _rate(count: int, base: float, target: int) -> float:
    if target <= 0 or count >= target:
        return base
    return base + (1.0 - base) * (1.0 - count / target)


async def test_sample_rate_ramps_up_when_store_is_small(monkeypatch):
    monkeypatch.setattr(app_config, "agent_sticker_memory_sample_rate", 0.5)
    monkeypatch.setattr(app_config, "agent_sticker_warmup_count", 30)
    # 空库: 必采
    assert sticker_memory.sample_rate_for(0) == pytest.approx(1.0)
    # 半库: 线性放大
    assert sticker_memory.sample_rate_for(15) == pytest.approx(_rate(15, 0.5, 30))
    # 达标及超额: 回落到底值
    assert sticker_memory.sample_rate_for(30) == pytest.approx(0.5)
    assert sticker_memory.sample_rate_for(500) == pytest.approx(0.5)


async def test_sample_rate_disabled_target(monkeypatch):
    monkeypatch.setattr(app_config, "agent_sticker_memory_sample_rate", 0.2)
    monkeypatch.setattr(app_config, "agent_sticker_warmup_count", 0)
    assert sticker_memory.sample_rate_for(0) == pytest.approx(0.2)
    monkeypatch.setattr(app_config, "agent_sticker_warmup_count", None)
    assert sticker_memory.sample_rate_for(0) == pytest.approx(0.2)
    assert sticker_memory.sample_rate_for(10**9) == pytest.approx(0.2)


async def test_prepare_gate_skipped_when_warmup_disabled(monkeypatch):
    """warmup 关闭 (None) 时不做库存门槛检查, 工具始终显示."""
    from kmua.plugins.agent.tools import prepare

    monkeypatch.setattr(app_config, "agent_sticker_memory", True)
    monkeypatch.setattr(app_config, "agent_sticker_warmup_count", None)
    td = ToolDefinition(name="send_sticker", description="", parameters_json_schema={})

    deps = datatype.ContextDeps(
        client=cast("PyrogramClient", SimpleNamespace()),
        user_id=1001,
        chat_id=-100123,
        message=cast(
            "pyrogram.types.Message",
            SimpleNamespace(id=1, guest_query_id=None),
        ),
    )
    ctx = RunContext(deps=deps, model=TestModel(), usage=RunUsage(), messages=[])

    monkeypatch.setattr(sticker_memory, "embedder", SimpleNamespace())

    from kmua.database.models import ChatConfig

    async def config_ok(chat_id):
        return ChatConfig(sticker_memory_enabled=True)

    monkeypatch.setattr(prepare.database, "get_chat_config", config_ok)

    async def count_zero(chat_id):
        return 0

    monkeypatch.setattr(sticker_vec, "count", count_zero)
    assert await prepare.prepare_sticker_tools(ctx, td) is not None


async def test_on_sticker_warmup_always_samples(monkeypatch):
    """库为空时, 每张贴纸都应进入处理流程 (概率 1.0)."""
    from kmua.plugins.agent import sticker_memory as sm

    monkeypatch.setattr(app_config, "agent", True)
    monkeypatch.setattr(app_config, "agent_sticker_memory", True)
    monkeypatch.setattr(app_config, "agent_sticker_memory_sample_rate", 0.3)
    monkeypatch.setattr(app_config, "agent_sticker_warmup_count", 30)

    monkeypatch.setattr(sm, "embedder", SimpleNamespace())
    monkeypatch.setattr(sm, "_description_agent", SimpleNamespace())

    from kmua.database.models import ChatConfig

    async def config_ok(chat_id):
        return ChatConfig(ai_reply=True, sticker_memory_enabled=True)

    monkeypatch.setattr(sm.database, "get_chat_config", config_ok)

    async def count_zero(chat_id):
        return 0

    monkeypatch.setattr(sm.sticker_vec, "count", count_zero)

    processed = []

    async def fake_process(client, sticker, chat_id):
        processed.append(chat_id)

    monkeypatch.setattr(sm, "_process_sticker", fake_process)

    spawned = []

    def fake_spawn(coro, name=""):
        spawned.append((coro, name))
        coro.close()

    monkeypatch.setattr(sm.common, "spawn", fake_spawn)
    message = cast(
        "object",
        SimpleNamespace(
            chat=SimpleNamespace(id=-100123),
            sticker=SimpleNamespace(
                file_unique_id="uid", file_id="fid", is_animated=False
            ),
        ),
    )

    # 强制 random_chance 采样成功/失败两条路径
    import kmua.common as common

    monkeypatch.setattr(common, "random_chance", lambda p: True)
    await sm.on_sticker(None, message)
    assert len(spawned) == 1

    # 库为空 => rate 1.0 => random_chance(1.0) 恒真, 无需强制
    monkeypatch.setattr(common, "random_chance", lambda p: p >= 1.0)
    await sm.on_sticker(None, message)
    assert len(spawned) == 2
    coro, _ = spawned[1]
    coro.close()  # 防止未 await 协程警告

    # 满库 => 底值 0.3, random_chance(0.3) 为 False 时跳过
    async def count_full(chat_id):
        return 100

    monkeypatch.setattr(sm.sticker_vec, "count", count_full)
    monkeypatch.setattr(common, "random_chance", lambda p: False)
    await sm.on_sticker(None, message)
    assert len(spawned) == 2

    # 库存低于目标 => rate > 底值
    rates: list[float] = []

    def record_chance(p):
        rates.append(p)
        return False

    monkeypatch.setattr(common, "random_chance", record_chance)

    async def count_ten(chat_id):
        return 10

    monkeypatch.setattr(sm.sticker_vec, "count", count_ten)
    await sm.on_sticker(None, message)
    assert rates == [pytest.approx(0.3 + 0.7 * (1 - 10 / 30))]


async def test_prepare_sticker_gate_uses_warmup_config(monkeypatch):
    """工具显示门槛 <20 硬编码改为读取 warmup 配置."""
    from kmua.plugins.agent.tools import prepare

    monkeypatch.setattr(app_config, "agent_sticker_memory", True)
    monkeypatch.setattr(app_config, "agent_sticker_warmup_count", 5)
    td = ToolDefinition(name="send_sticker", description="", parameters_json_schema={})

    deps = datatype.ContextDeps(
        client=cast("PyrogramClient", SimpleNamespace()),
        user_id=1001,
        chat_id=-100123,
        message=cast(
            "pyrogram.types.Message",
            SimpleNamespace(id=1, guest_query_id=None),
        ),
    )
    ctx = RunContext(deps=deps, model=TestModel(), usage=RunUsage(), messages=[])

    monkeypatch.setattr(sticker_memory, "embedder", SimpleNamespace())

    async def count_four(chat_id):
        return 4

    async def count_five(chat_id):
        return 5

    from kmua.database.models import ChatConfig

    async def config_ok(chat_id):
        return ChatConfig(sticker_memory_enabled=True)

    monkeypatch.setattr(prepare.database, "get_chat_config", config_ok)

    monkeypatch.setattr(sticker_vec, "count", count_four)
    assert await prepare.prepare_sticker_tools(ctx, td) is None

    monkeypatch.setattr(sticker_vec, "count", count_five)
    assert await prepare.prepare_sticker_tools(ctx, td) is not None
