"""Group-chat markdown assembly (input_format): grouping, media budget,
attribute integrity and the env header."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import cast

import pyrogram
from pyrogram.client import Client as _Client_t
from pyrogram.enums import ChatType, MessageMediaType

from kmua.plugins.agent import datatype, input_format


def _msg(
    id: int,
    sender_id: int | None = 1,
    first_name: str = "u",
    text: str = "",
    media=None,
    photo=None,
    date: datetime | None = None,
    reply_to_message_id: int | None = None,
    reply_to_top_message_id: int | None = None,
    sender_chat=None,
    is_bot: bool = False,
    from_user_id: int | None = None,
    voice=None,
    sticker=None,
) -> pyrogram.types.Message:
    from_user = None
    if sender_id is not None:
        from_user = SimpleNamespace(
            id=from_user_id if from_user_id is not None else sender_id,
            first_name=first_name,
            is_bot=is_bot,
        )
    return cast(
        pyrogram.types.Message,
        SimpleNamespace(
            id=id,
            chat=SimpleNamespace(id=-100123, type=ChatType.SUPERGROUP, title="测试群"),
            from_user=from_user,
            sender_chat=sender_chat,
            text=text,
            caption=None,
            entities=None,
            caption_entities=None,
            media=media,
            photo=photo,
            video=None,
            audio=None,
            voice=voice,
            document=None,
            sticker=sticker,
            poll=None,
            web_page=None,
            date=date or datetime(2026, 9, 5, 12, 0, id % 60),
            reply_to_message_id=reply_to_message_id,
            reply_to_top_message_id=reply_to_top_message_id,
            reply_to_message=None,
            service=None,
            new_chat_members=None,
            left_chat_member=None,
        ),
    )


class _Client:
    async def get_chat_member(self, chat_id, user_id):
        return SimpleNamespace(status=pyrogram.enums.ChatMemberStatus.MEMBER, user=None)

    async def download_media(self, *args, **kwargs):
        from io import BytesIO

        return BytesIO(b"fake-image-bytes")


def _ctx_info() -> datatype.ContextInfo:
    return datatype.ContextInfo(
        user_data=datatype.UserData(
            user_id=1001, full_name="u", username=None, config=None
        ),
        msg_id=999,
        current_time="2026-09-05T12:00:00",
        chat_type="SUPERGROUP",
    )


async def test_consecutive_sender_grouping(monkeypatch):
    monkeypatch.setattr(input_format.app_config, "agent_multimodal_input_count", 0)
    history = [
        _msg(1, sender_id=1, text="消息1"),
        _msg(2, sender_id=1, text="消息2"),
        _msg(3, sender_id=2, first_name="B", text="消息3"),
        _msg(4, sender_id=1, text="消息4"),
    ]
    current = _msg(5, sender_id=9, first_name="D", text="当前")
    result = await input_format.build_group_prompt(
        cast(_Client_t, _Client()), current, history, None
    )
    md = cast(str, result[0])
    # A header appears twice (split by B), B once: 4 headers, one per run
    assert md.count("u(1) | 真人 | 普通群员:") == 2
    assert md.count("B(2) | 真人 | 普通群员:") == 1
    assert "## 历史消息" in md
    assert "## 当前消息" in md


async def test_header_only_when_ctx_present(monkeypatch):
    monkeypatch.setattr(input_format.app_config, "agent_multimodal_input_count", 0)
    history = [_msg(1, text="早")]
    current = _msg(2, sender_id=9, text="现在")
    with_header = await input_format.build_group_prompt(
        cast(_Client_t, _Client()), current, history, _ctx_info()
    )
    assert "# 群聊 - 测试群" in cast(str, with_header[0])
    assert "当前时间: 2026" in cast(str, with_header[0])
    without_header = await input_format.build_group_prompt(
        cast(_Client_t, _Client()), current, history, None
    )
    assert "# 群聊" not in cast(str, without_header[0])


async def test_budget_newest_first_and_numbering(monkeypatch):
    monkeypatch.setattr(input_format.app_config, "agent_multimodal_input_count", 1)
    monkeypatch.setattr(
        input_format.app_config,
        "agent_multimodal_inputs",
        ["photo"],
    )

    def photo_payload(unique):
        return SimpleNamespace(file_id=f"file-{unique}", file_unique_id=unique)

    history = [
        _msg(
            1,
            text="",
            media=MessageMediaType.PHOTO,
            photo=photo_payload("old"),
        ),
        _msg(2, text="文本"),
        _msg(
            3,
            text="",
            media=MessageMediaType.PHOTO,
            photo=photo_payload("new"),
        ),
    ]
    current = _msg(4, sender_id=9, text="当前")
    result = await input_format.build_group_prompt(
        cast(_Client_t, _Client()), current, history, None
    )
    md = cast(str, result[0])
    # budget 1 -> newest history image (msg 3) wins, msg 1 degraded
    assert 'media_type="photo" image_number=1 text=""' in md
    assert 'media_type="photo" text=""' in md
    # one binary delivered
    assert len(result) == 2


async def test_file_unique_id_dedup(monkeypatch):
    monkeypatch.setattr(input_format.app_config, "agent_multimodal_input_count", 5)
    monkeypatch.setattr(input_format.app_config, "agent_multimodal_inputs", ["photo"])

    def photo_payload(unique):
        return SimpleNamespace(file_id=f"file-{unique}", file_unique_id=unique)

    history = [
        _msg(
            1,
            sender_id=1,
            text="",
            media=MessageMediaType.PHOTO,
            photo=photo_payload("same"),
        ),
        _msg(
            2,
            sender_id=2,
            first_name="B",
            text="",
            media=MessageMediaType.PHOTO,
            photo=photo_payload("same"),
        ),
    ]
    current = _msg(3, sender_id=9, text="当前")
    result = await input_format.build_group_prompt(
        cast(_Client_t, _Client()), current, history, None
    )
    md = cast(str, result[0])
    # same image content: both lines reference 图1, only one binary sent
    assert md.count("image_number=1") == 2
    assert len(result) == 2  # markdown + 1 binary


async def test_text_always_present_and_quoted(monkeypatch):
    monkeypatch.setattr(input_format.app_config, "agent_multimodal_input_count", 0)
    history = [
        _msg(1, text='含"引号"\n第二行'),
        _msg(
            2,
            text="",
            media=MessageMediaType.PHOTO,
            photo=SimpleNamespace(file_id="f", file_unique_id="u2"),
        ),
    ]
    current = _msg(3, sender_id=9, text="当前")
    result = await input_format.build_group_prompt(
        cast(_Client_t, _Client()), current, history, None
    )
    md = cast(str, result[0])
    assert 'text="含\\"引号\\"' in md
    assert '\n第二行"' in md  # newline kept inside the quoted value
    assert 'media_type="photo" image_number=1 text=""' in md


async def test_reply_chain_depth_attribute(monkeypatch):
    monkeypatch.setattr(input_format.app_config, "agent_multimodal_input_count", 0)
    current = _msg(
        9,
        sender_id=9,
        text="当前",
        reply_to_message_id=8,
        reply_to_top_message_id=None,
    )
    result = await input_format.build_group_prompt(
        cast(_Client_t, _Client()), current, [], None
    )
    assert "reply_chain_depth=1" not in cast(str, result[0])  # single reply: no hint


async def test_deep_reply_chain_hint(monkeypatch):
    monkeypatch.setattr(input_format.app_config, "agent_multimodal_input_count", 0)
    # reply_to_top_message_id present on the current message means the chain
    # continues beyond the direct reply
    current = _msg(
        9,
        sender_id=9,
        text="当前",
        reply_to_message_id=8,
        reply_to_top_message_id=5,
    )
    result = await input_format.build_group_prompt(
        cast(_Client_t, _Client()), current, [], None
    )
    assert "reply_chain_depth=" in cast(str, result[0])


async def test_service_message_sender(monkeypatch):
    monkeypatch.setattr(input_format.app_config, "agent_multimodal_input_count", 0)
    history = [
        _msg(
            1,
            sender_id=None,
            from_user_id=None,
            first_name="",
            text="",
        ),
    ]
    current = _msg(2, sender_id=9, text="当前")
    result = await input_format.build_group_prompt(
        cast(_Client_t, _Client()), current, history, None
    )
    assert "系统(系统) | 系统 | 系统:" in cast(str, result[0])


async def test_channel_sender_kind(monkeypatch):
    monkeypatch.setattr(input_format.app_config, "agent_multimodal_input_count", 0)
    history = [
        _msg(
            1,
            sender_id=-100999,
            sender_chat=SimpleNamespace(id=-100999, title="频道A"),
            text="频道消息",
        ),
    ]
    current = _msg(2, sender_id=9, text="当前")
    result = await input_format.build_group_prompt(
        cast(_Client_t, _Client()), current, history, None
    )
    assert "频道A(-100999) | 频道 | 频道:" in cast(str, result[0])


async def test_reply_block_one_level(monkeypatch):
    monkeypatch.setattr(input_format.app_config, "agent_multimodal_input_count", 0)
    replied = _msg(8, sender_id=2, first_name="B", text="被回复")
    current = _msg(9, sender_id=9, text="当前", reply_to_message_id=8)
    current.reply_to_message = replied

    result = await input_format.build_group_prompt(
        cast(_Client_t, _Client()), current, [], None
    )
    assert "当前用户所回复的消息:" in cast(str, result[0])
    assert "B(2)" in cast(str, result[0])
    assert "被回复" in cast(str, result[0])


async def test_voice_delivered_with_audio_mime(monkeypatch):
    """A voice message must ride as audio/* — never the photo jpeg default
    (regression: hardcoded image/jpeg caused provider 400)."""
    monkeypatch.setattr(input_format.app_config, "agent_multimodal_input_count", 5)
    monkeypatch.setattr(input_format.app_config, "agent_multimodal_inputs", ["audio"])
    voice = SimpleNamespace(
        file_id="voice-1", file_unique_id="vu1", mime_type="audio/ogg", file_size=1000
    )
    history = [
        _msg(
            1,
            text="",
            media=MessageMediaType.VOICE,
            voice=voice,
        ),
    ]
    current = _msg(2, sender_id=9, text="当前")
    result = await input_format.build_group_prompt(
        cast(_Client_t, _Client()), current, history, None
    )
    assert len(result) == 2
    binary = result[1]
    assert binary.media_type == "audio/ogg"


async def test_video_sticker_uses_first_frame(monkeypatch):
    """A video sticker delivers its extracted first frame as image/webp —
    never the raw webm (regression: raw webm caused provider 400)."""
    monkeypatch.setattr(input_format.app_config, "agent_multimodal_input_count", 5)
    monkeypatch.setattr(input_format.app_config, "agent_multimodal_inputs", ["photo"])
    sticker = SimpleNamespace(
        file_id="stk-1", file_unique_id="su1", is_video=True, is_animated=False
    )
    history = [
        _msg(
            1,
            text="",
            media=MessageMediaType.STICKER,
            sticker=sticker,
        ),
    ]
    current = _msg(2, sender_id=9, text="当前")

    frames: list[bytes] = []

    import kmua.common.utils as common_utils

    async def fake_frame(webm: bytes) -> bytes | None:
        frames.append(webm)
        return b"webp-frame"

    monkeypatch.setattr(common_utils, "webm_first_frame", fake_frame)
    result = await input_format.build_group_prompt(
        cast(_Client_t, _Client()), current, history, None
    )
    assert len(frames) == 1
    assert len(result) == 2
    assert result[1].media_type == "image/webp"
    assert result[1].data == b"webp-frame"
