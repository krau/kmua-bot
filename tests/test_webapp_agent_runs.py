"""Agent run trace API contracts.

The endpoints are read-only, so what they have to get right is what they return and
what they refuse: the list omits the heavy text, the detail lists every step, and a
single request step comes back with the messages the model actually saw.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from kmua.database import agent_trace as store
from tests.webapp_helpers import api_client, bearer, make_user

pytestmark = pytest.mark.usefixtures("initialised_db")

ADMIN_ID = 940_100
PLAIN_ID = 940_101

CHAT_ID = -1009401001
USER_ID = 940_102


@pytest.fixture(autouse=True)
async def clean_traces():
    import sqlalchemy

    from kmua.database.db import AsyncSessionFactory
    from kmua.database.models import AgentRun, AgentRunEvent

    async with AsyncSessionFactory() as session:
        async with session.begin():
            await session.execute(sqlalchemy.delete(AgentRunEvent))
            await session.execute(sqlalchemy.delete(AgentRun))
    yield


def _event(
    seq: int,
    kind: str,
    payload: dict | None = None,
    *,
    name: str | None = None,
    duration_ms: int | None = None,
    status: str = "ok",
    truncated: bool = False,
) -> store.AgentRunEventDraft:
    return store.AgentRunEventDraft(
        seq=seq,
        kind=kind,
        status=status,
        name=name,
        duration_ms=duration_ms,
        payload=payload,
        truncated=truncated,
    )


async def seed_run(
    *,
    kind: str = "chat",
    status: str = "ok",
    output_text: str = "the answer",
    error_message: str | None = None,
    started_at: datetime | None = None,
) -> int:
    """Write one run with a request/response pair and a tool round trip."""
    messages = [
        {"kind": "request", "parts": [{"content": "hi", "part_kind": "user-prompt"}]}
    ]
    now = started_at or datetime.now(UTC)
    draft = store.AgentRunDraft(
        kind=kind,
        status=status,
        chat_id=CHAT_ID,
        user_id=USER_ID,
        message_id=11,
        model_name="test-model",
        model_role="main",
        streaming=False,
        started_at=now,
        finished_at=now,
        duration_ms=12,
        events=(
            _event(
                1,
                "model_request",
                {
                    "model": "test-model",
                    "messages_total": 1,
                    "messages_prefix_len": 0,
                    "messages": messages,
                },
            ),
            _event(2, "model_response", {"model": "test-model"}, duration_ms=5),
            _event(
                3,
                "tool_call",
                {"tool_call_id": "c1", "args": {"text": "x"}},
                name="echo",
            ),
            _event(
                4,
                "tool_result",
                {"tool_call_id": "c1", "result": "echo:x"},
                name="echo",
                duration_ms=2,
            ),
        ),
        requests=2,
        tool_calls=1,
        input_tokens=100,
        output_tokens=20,
        cache_read_tokens=7,
        cache_write_tokens=3,
        output_kind="str",
        output_text=output_text,
        output_chars=len(output_text),
        error_class="RuntimeError" if error_message else None,
        error_message=error_message,
    )
    await store.record_trace([draft])
    run = await store.get_runs_page(1, 10)
    return run.items[0].id


async def test_the_list_filters_and_omits_the_heavy_fields():
    await make_user(ADMIN_ID, full_name="Trace Admin", global_admin=True)
    first = await seed_run()
    await seed_run(
        kind="followup_relevance", status="timeout", output_text="a relevance story"
    )
    await seed_run(kind="memory", status="rejected", output_text="")

    async with api_client() as client:
        headers = bearer(ADMIN_ID)
        page = await client.get("/api/admin/agent-runs", headers=headers)
        assert page.status_code == 200
        body = page.json()
        assert body["total"] == 3
        assert len(body["items"]) == 3
        assert "output_text" not in body["items"][0]
        assert "error_message" not in body["items"][0]
        assert body["items"][0]["model_name"] == "test-model"

        by_kind = await client.get(
            "/api/admin/agent-runs", params={"kind": "memory"}, headers=headers
        )
        assert by_kind.json()["total"] == 1

        by_status = await client.get(
            "/api/admin/agent-runs", params={"status": "timeout"}, headers=headers
        )
        assert by_status.json()["total"] == 1

        by_chat = await client.get(
            "/api/admin/agent-runs", params={"chat_id": CHAT_ID}, headers=headers
        )
        assert by_chat.json()["total"] == 3

        empty_chat = await client.get(
            "/api/admin/agent-runs", params={"chat_id": -1}, headers=headers
        )
        assert empty_chat.json()["total"] == 0

        by_user = await client.get(
            "/api/admin/agent-runs", params={"user_id": USER_ID}, headers=headers
        )
        assert by_user.json()["total"] == 3

        found = await client.get(
            "/api/admin/agent-runs", params={"q": "relevance story"}, headers=headers
        )
        assert found.json()["total"] == 1
        # The search covers the error text too, not just the output.
        broken = await seed_run(status="error", error_message="provider exploded")
        assert broken > 0
        by_error = await client.get(
            "/api/admin/agent-runs", params={"q": "exploded"}, headers=headers
        )
        assert by_error.json()["total"] == 1

        missing = await client.get(
            "/api/admin/agent-runs", params={"q": "nothing here"}, headers=headers
        )
        assert missing.json()["total"] == 0

        future = await client.get(
            "/api/admin/agent-runs",
            params={"since": "2999-01-01T00:00:00Z"},
            headers=headers,
        )
        assert future.json()["total"] == 0

    assert first > 0


async def test_the_detail_lists_steps_without_their_payloads():
    await make_user(ADMIN_ID, full_name="Trace Admin", global_admin=True)
    run_id = await seed_run(output_text="hello there", error_message="boom")

    async with api_client() as client:
        response = await client.get(
            f"/api/admin/agent-runs/{run_id}", headers=bearer(ADMIN_ID)
        )

    assert response.status_code == 200
    body = response.json()
    assert body["output_text"] == "hello there"
    assert body["error_message"] == "boom"
    assert body["output_chars"] == len("hello there")
    assert [event["seq"] for event in body["events"]] == [1, 2, 3, 4]
    assert [event["kind"] for event in body["events"]] == [
        "model_request",
        "model_response",
        "tool_call",
        "tool_result",
    ]
    assert "payload" not in body["events"][0]
    assert body["events"][3]["name"] == "echo"


async def test_a_request_step_returns_the_replayed_messages():
    await make_user(ADMIN_ID, full_name="Trace Admin", global_admin=True)
    run_id = await seed_run()

    async with api_client() as client:
        headers = bearer(ADMIN_ID)
        request_event = await client.get(
            f"/api/admin/agent-runs/{run_id}/events/1", headers=headers
        )
        tool_event = await client.get(
            f"/api/admin/agent-runs/{run_id}/events/4", headers=headers
        )

    assert request_event.status_code == 200
    body = request_event.json()
    assert body["kind"] == "model_request"
    assert body["messages"] == [
        {"kind": "request", "parts": [{"content": "hi", "part_kind": "user-prompt"}]}
    ]
    assert body["payload"]["messages_total"] == 1

    # Only requests carry a transcript; a tool step reports its payload instead.
    assert tool_event.status_code == 200
    assert tool_event.json()["messages"] is None
    assert tool_event.json()["payload"] == {"tool_call_id": "c1", "result": "echo:x"}


async def test_unknown_ids_are_not_found():
    await make_user(ADMIN_ID, full_name="Trace Admin", global_admin=True)

    async with api_client() as client:
        headers = bearer(ADMIN_ID)
        missing_run = await client.get("/api/admin/agent-runs/999999", headers=headers)
        run_id = await seed_run()
        missing_event = await client.get(
            f"/api/admin/agent-runs/{run_id}/events/99", headers=headers
        )

    assert missing_run.status_code == 404
    assert missing_run.json()["code"] == "NOT_FOUND"
    assert missing_event.status_code == 404
    assert missing_event.json()["code"] == "NOT_FOUND"


async def test_an_unknown_vocabulary_value_is_rejected():
    await make_user(ADMIN_ID, full_name="Trace Admin", global_admin=True)

    async with api_client() as client:
        headers = bearer(ADMIN_ID)
        bad_kind = await client.get(
            "/api/admin/agent-runs", params={"kind": "nonsense"}, headers=headers
        )
        bad_status = await client.get(
            "/api/admin/agent-runs", params={"status": "nonsense"}, headers=headers
        )

    assert bad_kind.status_code == 422
    assert bad_kind.json()["code"] == "VALIDATION_FAILED"
    assert bad_status.status_code == 422
    assert bad_status.json()["code"] == "VALIDATION_FAILED"


async def test_the_trace_is_admin_only():
    await make_user(PLAIN_ID, full_name="Plain User")

    async with api_client() as client:
        anonymous = await client.get("/api/admin/agent-runs")
        refused = await client.get("/api/admin/agent-runs", headers=bearer(PLAIN_ID))

    assert anonymous.status_code == 401
    assert anonymous.json()["code"] == "TOKEN_MISSING"
    assert refused.status_code == 403
    assert refused.json()["code"] == "ADMIN_REQUIRED"
