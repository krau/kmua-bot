"""Administrator statistics and runtime metric contracts."""

from __future__ import annotations

import pytest

from kmua.webapp.metrics import RuntimeMetrics
from tests.webapp_helpers import api_client, bearer, make_user

pytestmark = pytest.mark.usefixtures("initialised_db")

ADMIN_ID = 901_000


async def test_runtime_snapshot_reports_bounded_recent_windows():
    metrics = RuntimeMetrics()
    metrics.observe_loop_lag(0.012, stalled=False)
    metrics.observe_loop_lag(0.090, stalled=True)
    metrics.observe_telegram_update("UpdateNewMessage")
    metrics.observe_api_request(0.025, 200)
    metrics.observe_group_activity(-100_001, "ai_chat")
    metrics.observe_group_activity(-100_001, "ai_chat")
    metrics.observe_group_activity(-100_002, "bottle_pick")

    snapshot = metrics.snapshot()

    assert snapshot.uptime_seconds >= 0
    assert snapshot.loop_lag_ms == pytest.approx(90)
    assert snapshot.loop_lag_p95_ms == pytest.approx(90)
    assert snapshot.loop_lag_max_ms == pytest.approx(90)
    assert snapshot.loop_stalls == 1
    assert snapshot.telegram_updates["60"] == 1
    assert snapshot.api_requests["300"] == 1
    assert snapshot.api_latency_ms["p95"] == pytest.approx(25)

    assert snapshot.telegram_update_types["UpdateNewMessage"] == 1

    assert snapshot.group_activity == [
        {"chat_id": -100_001, "events": 2},
        {"chat_id": -100_002, "events": 1},
    ]
    assert snapshot.feature_calls == {"ai_chat": 2, "bottle_pick": 1}
async def test_admin_stats_includes_runtime_snapshot(monkeypatch):
    await make_user(ADMIN_ID, full_name="Metrics Admin", global_admin=True)

    async with api_client() as client:
        response = await client.get("/api/admin/stats", headers=bearer(ADMIN_ID))

    assert response.status_code == 200
    runtime = response.json()["runtime"]
    dashboard = response.json()["dashboard"]
    assert dashboard["user_structure"]["real_users"] >= 1
    assert dashboard["recent"]["days"] == 7
    assert set(dashboard["bottle_interactions"]) == {"picks", "reports", "replies"}
    assert runtime["uptime_seconds"] >= 0
    assert runtime["max_rss_bytes"] > 0
    assert set(runtime["telegram_updates"]) == {"60", "300", "900"}
    assert set(runtime["api_requests"]) == {"60", "300", "900"}
    assert set(runtime["api_latency_ms"]) == {"p95"}
    assert "UpdateNewMessage" in runtime["telegram_update_types"]
    assert isinstance(runtime["group_activity"], list)
    assert isinstance(runtime["feature_calls"], dict)
