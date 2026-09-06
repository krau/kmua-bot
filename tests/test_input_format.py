"""Group-chat markdown assembly (input_format): grouping, media budget,
attribute integrity and the env header."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import cast

import pyrogram
from pyrogram.client import Client as _Client_t
from pyrogram.enums import ChatType, MessageMediaType

from kmua.plugins.agent import datatype, input_format, state


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


class _CountingClient:
    """Client wrapper recording every download_media call."""

    def __init__(self):
        self._inner = _Client()
        self.downloads = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    async def get_chat_member(self, chat_id, user_id):
        return await self._inner.get_chat_member(chat_id, user_id)

    async def download_media(self, *args, **kwargs):
        self.downloads += 1
        return await self._inner.download_media(*args, **kwargs)


def _ctx_info() -> datatype.ContextInfo:
    return datatype.ContextInfo(
        user_data=datatype.UserData(
            user_id=1001, full_name="u", username=None, config=None
        ),
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
    result, _ = await input_format.build_group_prompt(
        cast(_Client_t, _Client()), current, history, None
    )
    md = cast(str, result[0])
    # A header appears twice (split by B), B once: 4 headers, one per run
    assert md.count("u(1) | 真人 | 群员:") == 2
    assert md.count("B(2) | 真人 | 群员:") == 1
    assert "## 历史消息" in md
    assert "## 当前消息" in md


async def test_env_header_in_every_prompt(monkeypatch):
    """The stamp (chat title + current time) must appear on every prompt;
    ContextInfo extras only on the first prompt (ctx present)."""
    monkeypatch.setattr(input_format.app_config, "agent_multimodal_input_count", 0)
    history = [_msg(1, text="早")]
    current = _msg(2, sender_id=9, text="现在")
    with_ctx, _ = await input_format.build_group_prompt(
        cast(_Client_t, _Client()), current, history, _ctx_info()
    )
    md = cast(str, with_ctx[0])
    assert "# 群聊 - 测试群" in md
    assert "当前时间: " in md
    without_ctx, _ = await input_format.build_group_prompt(
        cast(_Client_t, _Client()), current, history, None
    )
    md = cast(str, without_ctx[0])
    assert "# 群聊 - 测试群" in md
    assert "当前时间: " in md
    assert "用户信息" not in md
    assert "群组信息" not in md


async def test_env_header_carries_ctx_extras(monkeypatch):
    """Memory and the affection append_prompt ride only in the ctx header."""
    ctx = _ctx_info()
    ctx.memory_about_user = datatype.ChatMemoryy(
        disposition=["高冷"],
        interests=[],
        doings=[],
        works=[],
        wishes=[],
        worries=[],
        skills=[],
        attitudes_to_you=[],
        experiences_with_you=[],
        extra_info=[],
    )
    ctx.append_prompt = "好感度提示"
    history = [_msg(1, text="早")]
    current = _msg(2, sender_id=9, text="现在")
    result, _ = await input_format.build_group_prompt(
        cast(_Client_t, _Client()), current, history, ctx
    )
    md = cast(str, result[0])
    assert "关于用户的记忆: (性格: 高冷)" in md
    assert "附加提示: 好感度提示" in md


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
    result, _ = await input_format.build_group_prompt(
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
    result, _ = await input_format.build_group_prompt(
        cast(_Client_t, _Client()), current, history, None
    )
    md = cast(str, result[0])
    # same image content: first line gets the fresh number, the later copy
    # is a pure reference (no second binary, no duplicate number)
    assert md.count("image_number=1") == 1
    assert "referenced_media=1" in md
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
    result, _ = await input_format.build_group_prompt(
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
    result, _ = await input_format.build_group_prompt(
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
    result, _ = await input_format.build_group_prompt(
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
    result, _ = await input_format.build_group_prompt(
        cast(_Client_t, _Client()), current, history, None
    )
    assert "系统(系统) | 系统 | 系统:" in cast(str, result[0])


async def test_service_message_text_rendered(monkeypatch):
    """Service events (join/leave/title change) render readable text via
    _service_text instead of an empty text attribute."""
    monkeypatch.setattr(input_format.app_config, "agent_multimodal_input_count", 0)
    joined = _msg(1, sender_id=2, first_name="A", text="")
    joined.service = pyrogram.enums.MessageServiceType.NEW_CHAT_MEMBERS
    joined.new_chat_members = [SimpleNamespace(first_name="新人")]
    history = [joined]
    current = _msg(2, sender_id=9, text="当前")
    result, _ = await input_format.build_group_prompt(
        cast(_Client_t, _Client()), current, history, None
    )
    md = cast(str, result[0])
    assert 'text="NEW_CHAT_MEMBERS A 新人"' in md
    assert 'text=""' not in md.split("## 当前消息")[0]


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
    result, _ = await input_format.build_group_prompt(
        cast(_Client_t, _Client()), current, history, None
    )
    assert "频道A(-100999) | 频道 | 频道:" in cast(str, result[0])


async def test_reply_block_one_level(monkeypatch):
    monkeypatch.setattr(input_format.app_config, "agent_multimodal_input_count", 0)
    replied = _msg(8, sender_id=2, first_name="B", text="被回复")
    current = _msg(9, sender_id=9, text="当前", reply_to_message_id=8)
    current.reply_to_message = replied

    result, _ = await input_format.build_group_prompt(
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
    result, _ = await input_format.build_group_prompt(
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
    result, _ = await input_format.build_group_prompt(
        cast(_Client_t, _Client()), current, history, None
    )
    assert len(frames) == 1
    assert len(result) == 2
    assert result[1].media_type == "image/webp"
    assert result[1].data == b"webp-frame"


async def test_seen_nearby_omitted(monkeypatch):
    """Messages at or below coverage.last_message_id are dropped from the
    history section; newer ones still render (dedup cuts repeated input)."""
    monkeypatch.setattr(input_format.app_config, "agent_multimodal_input_count", 5)
    coverage = state.PromptCoverage(last_message_id=2)
    history = [
        _msg(1, sender_id=1, first_name="A", text="旧1"),
        _msg(2, sender_id=2, first_name="B", text="旧2"),
        _msg(3, sender_id=3, first_name="C", text="新3"),
    ]
    current = _msg(4, sender_id=9, text="当前")
    result, meta = await input_format.build_group_prompt(
        cast(_Client_t, _Client()), current, history, None, coverage=coverage
    )
    md = cast(str, result[0])
    assert "id=1 " not in md
    assert "id=2 " not in md
    assert "id=3 " in md
    assert meta == {}


async def test_seen_media_not_downloaded(monkeypatch):
    """A media message already covered is skipped entirely: no download,
    no binary, no image_number (regression: repeated downloads and tokens)."""
    monkeypatch.setattr(input_format.app_config, "agent_multimodal_input_count", 5)
    coverage = state.PromptCoverage(last_message_id=1, sent_media={"u1": 1})
    history = [
        _msg(
            1,
            text="",
            media=MessageMediaType.PHOTO,
            photo=SimpleNamespace(file_id="f1", file_unique_id="u1"),
        )
    ]
    current = _msg(2, sender_id=9, text="当前")
    with _CountingClient() as client:
        result, meta = await input_format.build_group_prompt(
            cast(_Client_t, client), current, history, None, coverage=coverage
        )
    assert client.downloads == 0
    assert len(result) == 1
    assert "image_number" not in cast(str, result[0])
    assert meta == {}


async def test_reply_to_seen_image_references_number(monkeypatch):
    """Replying to an image already delivered references its old image_number
    instead of downloading again."""
    monkeypatch.setattr(input_format.app_config, "agent_multimodal_input_count", 5)
    coverage = state.PromptCoverage(last_message_id=1, sent_media={"u1": 1})
    replied = _msg(
        1,
        sender_id=2,
        text="旧图",
        media=MessageMediaType.PHOTO,
        photo=SimpleNamespace(file_id="f1", file_unique_id="u1"),
    )
    current = _msg(2, sender_id=9, text="当前", reply_to_message_id=1)
    current.reply_to_message = replied
    with _CountingClient() as client:
        result, meta = await input_format.build_group_prompt(
            cast(_Client_t, client), current, [], None, coverage=coverage
        )
    assert client.downloads == 0
    md = cast(str, result[0])
    assert "消息图号: 图1" in md
    assert len(result) == 1
    assert meta == {}  # references never advance the number cursor


async def test_resent_photo_references_old_number(monkeypatch):
    """A newer message re-sending the same unique image (forward/re-send)
    references the old number and skips the download."""
    monkeypatch.setattr(input_format.app_config, "agent_multimodal_input_count", 5)
    coverage = state.PromptCoverage(last_message_id=1, sent_media={"u1": 1})
    current = _msg(
        2,
        sender_id=9,
        text="重发",
        media=MessageMediaType.PHOTO,
        photo=SimpleNamespace(file_id="f2", file_unique_id="u1"),
    )
    with _CountingClient() as client:
        result, meta = await input_format.build_group_prompt(
            cast(_Client_t, client), current, [], None, coverage=coverage
        )
    assert client.downloads == 0
    md = cast(str, result[0])
    assert "消息图号: 图1" in md
    assert meta == {}  # reference only: nothing freshly downloaded


async def test_fresh_media_still_delivered(monkeypatch):
    """Newer-than-cursor media is downloaded and numbered as usual, and its
    unique id lands in the returned media meta for cursor advancement."""
    monkeypatch.setattr(input_format.app_config, "agent_multimodal_input_count", 5)
    coverage = state.PromptCoverage(last_message_id=1)
    history = [
        _msg(
            2,
            sender_id=2,
            first_name="C",
            text="新",
            media=MessageMediaType.PHOTO,
            photo=SimpleNamespace(file_id="f2", file_unique_id="u2"),
        )
    ]
    current = _msg(3, sender_id=9, text="当前")
    with _CountingClient() as client:
        result, meta = await input_format.build_group_prompt(
            cast(_Client_t, client), current, history, None, coverage=coverage
        )
    assert client.downloads == 1
    assert len(result) == 2
    assert meta == {"u2": 1}


async def test_advance_coverage_merges_and_caps(monkeypatch):
    """advance_prompt_coverage grows the cursor, appends media, and resets to
    the latest turn when the media map exceeds its cap."""
    from kmua.common.memory_store import memttlcache
    from kmua.plugins.agent.runner import advance_prompt_coverage

    await memttlcache.delete(state.prompt_coverage_key(-100, 7))
    await advance_prompt_coverage(
        -100, 7, state.PromptCoverage(last_message_id=10, sent_media={"a": 1})
    )
    cov = await memttlcache.get(state.prompt_coverage_key(-100, 7))
    assert cov.last_message_id == 10
    assert cov.sent_media == {"a": 1}
    assert cov.next_number == 2  # monotonic numbering past the delivered set
    # a later, smaller cursor never regresses
    await advance_prompt_coverage(-100, 7, state.PromptCoverage(last_message_id=8))
    cov = await memttlcache.get(state.prompt_coverage_key(-100, 7))
    assert cov.last_message_id == 10
    # cap: overflow keeps only the newest turn's media
    await advance_prompt_coverage(
        -100,
        7,
        state.PromptCoverage(
            last_message_id=11,
            sent_media={f"k{i}": i for i in range(300)},
        ),
    )
    cov = await memttlcache.get(state.prompt_coverage_key(-100, 7))
    assert len(cov.sent_media) == 300  # replaced wholesale with this turn's set
    assert cov.last_message_id == 11


async def test_no_number_collision_across_turns(monkeypatch):
    """A fresh image and a re-sent image in the same turn must not share a
    number: fresh numbers start above every previously delivered number and
    references keep their old, strictly smaller number."""
    monkeypatch.setattr(input_format.app_config, "agent_multimodal_input_count", 5)
    coverage = state.PromptCoverage(
        last_message_id=2, sent_media={"puA": 1}, next_number=2
    )
    history = [
        _msg(
            3,
            text="新图B",
            media=MessageMediaType.PHOTO,
            photo=SimpleNamespace(file_id="pB", file_unique_id="puB"),
        ),
        _msg(
            4,
            text="重发A",
            media=MessageMediaType.PHOTO,
            photo=SimpleNamespace(file_id="pA", file_unique_id="puA"),
        ),
    ]
    current = _msg(5, sender_id=9, text="当前")
    with _CountingClient() as client:
        result, meta = await input_format.build_group_prompt(
            cast(_Client_t, client), current, history, None, coverage=coverage
        )
    md = cast(str, result[0])
    assert client.downloads == 1  # only B downloaded
    assert md.count("image_number=2") == 1
    assert "referenced_media=1" in md
    assert len(result) == 2
    assert meta == {"puB": 2}  # only the fresh image advances the cursor


async def test_stale_next_number_never_collides(monkeypatch):
    """Defensive: an old coverage snapshot with next_number=1 and existing
    media must still number a fresh image above all delivered numbers."""
    monkeypatch.setattr(input_format.app_config, "agent_multimodal_input_count", 5)
    coverage = state.PromptCoverage(last_message_id=1, sent_media={"puA": 7})
    history = [
        _msg(
            2,
            text="新图",
            media=MessageMediaType.PHOTO,
            photo=SimpleNamespace(file_id="pN", file_unique_id="puN"),
        )
    ]
    current = _msg(3, sender_id=9, text="当前")
    result, meta = await input_format.build_group_prompt(
        cast(_Client_t, _Client()), current, history, None, coverage=coverage
    )
    md = cast(str, result[0])
    assert "image_number=8" in md
    assert meta == {"puN": 8}


async def test_transcribe_folds_by_occurrence(monkeypatch):
    """Transcription must land on the matching image_number attribute even
    when numbers are not 1..N (references use referenced_media instead, so
    they never shadow a fresh image slot)."""
    markdown = (
        "## 历史消息\n"
        '    - <msg id=1 media_type="photo" referenced_media=1 text="">\n'
        '    - <msg id=3 media_type="photo" image_number=5 text="">\n'
        "## 当前消息\n"
        "消息内容: x\n"
    )
    out = input_format.apply_transcriptions([markdown, "b1"], ["转述A", "转述B"])
    md = cast(str, out[0])
    # only one fresh slot exists: the second transcription has no target
    assert 'image_number=5 transcribed="转述A" ' in md
    assert "转述B" not in md
