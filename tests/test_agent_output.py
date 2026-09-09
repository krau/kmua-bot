"""Agent output delivery as Telegram rich messages."""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import pyrogram
import pyrogram.enums
import pytest
from pyrogram.client import Client
from pyrogram.raw.functions.messages.send_message import SendMessage as _RawSendMessage
from pyrogram.raw.types.input_rich_message_html import (
    InputRichMessageHTML as _RawInputRichMessageHTML,
)
from pyrogram.raw.types.update_message_id import UpdateMessageID as _RawUpdateMessageID
from pyrogram.raw.types.update_short_sent_message import (
    UpdateShortSentMessage as _RawUpdateShortSentMessage,
)
from pyrogram.raw.types.updates_t import Updates as _RawUpdates
from pyrogram.types import Message

from kmua.common.memory_store import memttlcache
from kmua.common.rich_message import message_plain_text, rich_html_plain_text
from kmua.config import app_config
from kmua.plugins.agent import output, state
from kmua.plugins.agent.styling import convert_md_chunks, convert_rich_md


class _FakeClient:
    def __init__(
        self,
        send_result: object = None,
        send_error: Exception | None = None,
        fail_on_call: int | None = None,
        edit_error: Exception | None = None,
    ) -> None:
        self.invoked: list[object] = []
        self.edits: list[dict] = []
        self._send_result = send_result
        self._send_error = send_error
        self._fail_on_call = fail_on_call
        self._send_calls = 0
        self._edit_error = edit_error

    async def resolve_peer(self, peer_id):  # type: ignore[no-untyped-def]
        return SimpleNamespace(user_id=peer_id)

    def rnd_id(self) -> int:
        return 1

    async def invoke(self, query):  # type: ignore[no-untyped-def]
        self.invoked.append(query)
        if isinstance(query, _RawSendMessage):
            self._send_calls += 1
            if self._send_error is not None and (
                self._fail_on_call is None or self._send_calls == self._fail_on_call
            ):
                raise self._send_error
        return self._send_result

    async def edit_message_text(self, chat_id, message_id, **kwargs):  # type: ignore[no-untyped-def]
        self.edits.append({"chat_id": chat_id, "message_id": message_id, **kwargs})
        if self._edit_error is not None:
            raise self._edit_error


class _FakeMessage:
    def __init__(
        self,
        message_id: int = 42,
        chat_id: int = -100777,
        fail_texts: set[str] | None = None,
    ) -> None:
        self.id = message_id
        self._fail_texts = fail_texts or set()
        self.chat = SimpleNamespace(id=chat_id, type=pyrogram.enums.ChatType.SUPERGROUP)
        self.sender_chat = None
        self.from_user = SimpleNamespace(id=777)
        self.text = "hi"
        self.caption = None
        self.message_thread_id = None
        self.direct_messages_topic_id = None
        self.replies: list[dict] = []
        self.actions: list = []
        self._next_id = 900

    async def reply_text(self, text, **kwargs):  # type: ignore[no-untyped-def]
        if text in self._fail_texts:
            raise RuntimeError("reply_text failed")
        self._next_id += 1
        self.replies.append({"text": text, "id": self._next_id, **kwargs})
        return SimpleNamespace(id=self._next_id, text=text)

    async def reply_chat_action(self, action):  # type: ignore[no-untyped-def]
        self.actions.append(action)


def _rich_sends(client: _FakeClient) -> list[_RawSendMessage]:
    return [query for query in client.invoked if isinstance(query, _RawSendMessage)]


def _updates_with_message_id(message_id: int) -> _RawUpdates:
    return _RawUpdates(
        updates=[_RawUpdateMessageID(id=message_id, random_id=1)],
        users=[],
        chats=[],
        date=0,
        seq=0,
    )


@pytest.fixture(autouse=True)
async def _reset_rich_breaker():
    await memttlcache.delete(output._RICH_FAILURE_KEY)
    await memttlcache.delete(output._RICH_DISABLED_KEY)
    yield
    await memttlcache.delete(output._RICH_FAILURE_KEY)
    await memttlcache.delete(output._RICH_DISABLED_KEY)


def test_convert_rich_md_keeps_structures():
    payloads = convert_rich_md(
        "# 标题\n\n| a | b |\n|:--|--:|\n| 1 | 2 |\n\n$$x^2$$\n\n- [x] 完成"
    )
    assert len(payloads) == 1
    html = payloads[0].html
    assert html is not None
    assert "<h1>" in html
    assert "<table>" in html
    assert "<tg-math-block>" in html
    assert "✅ 完成" in html


def test_convert_rich_md_splits_long_text():
    text = "\n\n".join(f"段落 {i}: " + "内容" * 40 for i in range(200))
    payloads = convert_rich_md(text)
    assert len(payloads) > 1
    assert all(payload.html is not None for payload in payloads)
    assert all(len(payload.html.encode()) <= 32768 for payload in payloads)  # type: ignore[union-attr]


def test_message_plain_text_renders_rich_blocks():
    # kurigram annotates RichText/RichBlock params narrowly; runtime accepts
    # str and list values (its own parser produces them).
    rich = pyrogram.types.RichMessage(
        blocks=[  # type: ignore[arg-type]
            pyrogram.types.RichBlockSectionHeading(text="标题", size=1),  # type: ignore[arg-type]
            pyrogram.types.RichBlockParagraph(
                text=["正文 ", pyrogram.types.RichTextBold(text="粗体")]  # type: ignore[arg-type]
            ),
            pyrogram.types.RichBlockTable(
                cells=[
                    [
                        pyrogram.types.RichBlockTableCell(text="a"),  # type: ignore[arg-type]
                        pyrogram.types.RichBlockTableCell(text="b"),  # type: ignore[arg-type]
                    ]
                ]
            ),
            pyrogram.types.RichBlockList(
                items=[
                    pyrogram.types.RichBlockListItem(
                        label="1.",
                        blocks=[pyrogram.types.RichBlockParagraph(text="第一")],  # type: ignore[arg-type,list-item]
                    )
                ]
            ),
        ]
    )
    message = SimpleNamespace(text="", caption=None, rich_message=rich)

    assert (
        message_plain_text(cast(Message, message)) == "标题\n正文 粗体\na | b\n1. 第一"
    )


def test_message_plain_text_keeps_plain_text():
    message = SimpleNamespace(text="普通消息", caption=None, rich_message=None)

    assert message_plain_text(cast(Message, message)) == "普通消息"


async def test_reply_output_sends_rich_message(monkeypatch):
    client = _FakeClient(send_result=_updates_with_message_id(555))
    message = _FakeMessage()
    await output.reply_output(
        cast(Client, client),
        cast(Message, message),
        "# 标题\n\n| a | b |\n|---|---|\n| 1 | 2 |",
    )

    sends = _rich_sends(client)
    assert len(sends) == 1
    assert sends[0].message == ""
    payload = sends[0].rich_message
    assert isinstance(payload, _RawInputRichMessageHTML)
    assert "<table>" in payload.html
    assert message.replies == []
    cached = await memttlcache.get(state.bot_last_reply_key(message.chat.id))
    assert cached is not None
    assert cached.message_id == 555
    assert cached.reply_text.startswith("# 标题")


async def test_reply_output_falls_back_to_entities_when_rich_send_fails():
    client = _FakeClient(send_error=RuntimeError("boom"))
    message = _FakeMessage()
    await output.reply_output(
        cast(Client, client), cast(Message, message), "# 标题\n\n正文"
    )

    # Whole answer goes out as one message, not the old paragraph chunks.
    assert len(message.replies) == 1
    assert message.replies[0]["entities"]
    assert "标题" in message.replies[0]["text"]
    assert "正文" in message.replies[0]["text"]
    cached = await memttlcache.get(state.bot_last_reply_key(message.chat.id))
    assert cached is not None
    assert cached.message_id == message.replies[-1]["id"]


async def test_reply_output_plain_fallback_splits_only_at_length_limit(monkeypatch):
    monkeypatch.setattr(app_config, "agent_rich_output", False)
    client = _FakeClient()
    message = _FakeMessage()
    text = "\n\n".join(f"段落 {i}: " + "内容" * 60 for i in range(60))
    assert len(text) > 4096

    await output.reply_output(cast(Client, client), cast(Message, message), text)

    assert len(message.replies) > 1
    assert all(len(reply["text"]) <= 4096 for reply in message.replies)


async def test_reply_output_falls_back_when_rich_conversion_empty(monkeypatch):
    monkeypatch.setattr(output, "convert_rich_md", lambda text: [])
    client = _FakeClient()
    message = _FakeMessage()
    await output.reply_output(cast(Client, client), cast(Message, message), "**粗体**")

    assert _rich_sends(client) == []
    assert message.replies


async def test_reply_output_respects_disabled_rich(monkeypatch):
    monkeypatch.setattr(app_config, "agent_rich_output", False)
    client = _FakeClient()
    message = _FakeMessage()
    await output.reply_output(cast(Client, client), cast(Message, message), "**粗体**")

    assert _rich_sends(client) == []
    assert message.replies


async def test_streaming_output_sends_and_finalizes_rich():
    client = _FakeClient(
        send_result=_RawUpdateShortSentMessage(id=777, pts=1, pts_count=1, date=0)
    )
    message = _FakeMessage()
    streaming = output.StreamingOutput(cast(Client, client), cast(Message, message))
    await streaming.append_delta("# 标题\n\n| a | b |\n|---|---|\n| 1 | 2 |")
    await streaming.finalize()

    sends = _rich_sends(client)
    assert len(sends) == 1
    assert streaming.reply_message_id == 777
    assert client.edits
    final_edit = client.edits[-1]
    assert final_edit["message_id"] == 777
    assert isinstance(final_edit["rich_message"], pyrogram.types.InputRichMessage)
    cached = await memttlcache.get(state.bot_last_reply_key(message.chat.id))
    assert cached is not None
    assert cached.message_id == 777


def test_rich_html_plain_text_drops_formatting():
    assert (
        rich_html_plain_text("<h1>标题</h1><p>正文 <b>粗</b><br/>换行</p><hr/>尾")
        == "标题\n正文 粗\n换行\n\n尾"
    )
    assert rich_html_plain_text("") == ""


async def test_reply_output_records_rich_original_message():
    client = _FakeClient(send_result=_updates_with_message_id(555))
    message = _FakeMessage()
    message.text = ""
    message.rich_message = pyrogram.types.RichMessage(  # type: ignore[attr-defined]
        blocks=[  # type: ignore[arg-type]
            pyrogram.types.RichBlockParagraph(text="用户的富文本消息")  # type: ignore[arg-type]
        ]
    )

    await output.reply_output(cast(Client, client), cast(Message, message), "**回复**")

    cached = await memttlcache.get(state.bot_last_reply_key(message.chat.id))
    assert cached is not None
    assert cached.original_user_message == "用户的富文本消息"


async def test_reply_output_sends_plain_tail_when_rich_send_partially_fails():
    client = _FakeClient(
        send_result=_updates_with_message_id(555),
        send_error=RuntimeError("boom"),
        fail_on_call=2,
    )
    message = _FakeMessage()
    text = "\n\n".join(f"段落 {i}: " + "内容" * 60 for i in range(200))
    assert len(convert_rich_md(text)) > 1

    await output.reply_output(cast(Client, client), cast(Message, message), text)

    assert len(_rich_sends(client)) == 2  # first payload delivered, second failed
    assert message.replies  # the undelivered tail still goes out
    assert "段落 199" in "".join(reply["text"] for reply in message.replies)


async def test_reply_output_pauses_rich_after_repeated_failures():
    client = _FakeClient(send_error=RuntimeError("boom"))
    message = _FakeMessage()
    for _ in range(output._RICH_FAILURE_LIMIT):
        await output.reply_output(
            cast(Client, client), cast(Message, message), "**粗体**"
        )
    assert len(_rich_sends(client)) == output._RICH_FAILURE_LIMIT

    await output.reply_output(cast(Client, client), cast(Message, message), "**粗体**")

    assert len(_rich_sends(client)) == output._RICH_FAILURE_LIMIT
    assert message.replies


async def test_occasional_rich_failures_do_not_trip_breaker():
    failing = _FakeClient(send_error=RuntimeError("boom"))
    good = _FakeClient(send_result=_updates_with_message_id(555))
    message = _FakeMessage()
    for _ in range(output._RICH_FAILURE_LIMIT - 1):
        await output.reply_output(
            cast(Client, failing), cast(Message, message), "**粗体**"
        )
    await output.reply_output(cast(Client, good), cast(Message, message), "**粗体**")
    await output.reply_output(cast(Client, failing), cast(Message, message), "**粗体**")

    attempts = len(_rich_sends(failing))
    await output.reply_output(cast(Client, failing), cast(Message, message), "**粗体**")

    assert len(_rich_sends(failing)) == attempts + 1


async def test_streaming_output_raises_when_rich_id_missing():
    client = _FakeClient()  # response carries no message id
    message = _FakeMessage()
    streaming = output.StreamingOutput(cast(Client, client), cast(Message, message))
    await streaming.append_delta("# 标题\n\n正文")

    with pytest.raises(RuntimeError):
        await streaming.finalize()

    assert len(_rich_sends(client)) == 1


async def test_streaming_finalize_sends_overflow_when_final_edit_fails():
    client = _FakeClient(
        send_result=_updates_with_message_id(555),
        edit_error=RuntimeError("edit failed"),
    )
    message = _FakeMessage()
    streaming = output.StreamingOutput(cast(Client, client), cast(Message, message))
    text = "\n\n".join(f"段落 {i}: " + "内容" * 60 for i in range(200))
    payloads = convert_rich_md(text)
    assert len(payloads) > 1

    await streaming.append_delta(text)
    await streaming.finalize()

    # first payload opened the stream, the rest still went out as overflow
    assert len(_rich_sends(client)) == len(payloads)


async def test_plain_fallback_skips_failed_chunk_and_keeps_going(monkeypatch):
    monkeypatch.setattr(app_config, "agent_rich_output", False)
    client = _FakeClient()
    text = "\n\n".join(f"段落 {i}: " + "内容" * 60 for i in range(60))
    chunks = [chunk for chunk, _ in convert_md_chunks(text)]
    assert len(chunks) > 1
    message = _FakeMessage(fail_texts={chunks[0]})

    await output.reply_output(cast(Client, client), cast(Message, message), text)

    delivered = [reply["text"] for reply in message.replies]
    assert chunks[1] in delivered
    assert chunks[-1] in delivered
