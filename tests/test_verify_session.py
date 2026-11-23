from datetime import UTC, datetime, timedelta

from kmua.database.models import VerificationSession
from kmua.plugins.verify import session as verify_session


async def test_sticker_session_records_current_message(monkeypatch) -> None:
    updates: list[object] = []

    async def capture_update(session_row) -> None:
        updates.append(session_row)

    monkeypatch.setattr(
        verify_session.database, "update_verification_session", capture_update
    )
    session_row = VerificationSession(
        id=950_001,
        chat_id=-1001,
        user_id=42,
        method="sticker",
        payload={},
        attempts_left=1,
        expires_at=datetime.now(UTC) + timedelta(minutes=2),
    )
    verify_session._register(session_row)
    try:
        await verify_session.record_window_message(-1001, 42, 101)
        await verify_session.record_window_message(-1001, 42, 101)
        await verify_session.record_window_message(-1001, 42, 102)
    finally:
        verify_session._unregister(session_row.id)

    assert session_row.payload[verify_session._WINDOW_MESSAGE_IDS_KEY] == [101, 102]
    assert len(updates) == 2


async def test_window_cleanup_deletes_only_recorded_messages(monkeypatch) -> None:
    calls: list[tuple[int, list[int]]] = []

    async def capture_delete(chat_id: int, message_ids: list[int]) -> None:
        calls.append((chat_id, message_ids))

    monkeypatch.setattr(verify_session.client, "delete_messages", capture_delete)
    session_row = VerificationSession(
        id=950_002,
        chat_id=-1001,
        user_id=42,
        method="sticker",
        payload={verify_session._WINDOW_MESSAGE_IDS_KEY: [101, 102]},
        attempts_left=1,
        expires_at=datetime.now(UTC) + timedelta(minutes=2),
    )

    await verify_session._delete_user_messages_in_window(session_row)

    assert calls == [(-1001, [101, 102])]
