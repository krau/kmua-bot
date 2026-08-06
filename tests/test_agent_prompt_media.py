"""get_input_prompt media handling: unsupported media must leave a visible
placeholder so the model never answers as if the message had no media."""

from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace

from pyrogram.enums import ChatType, MessageMediaType

from kmua.config import app_config
from kmua.plugins.agent import prompt


def _media_msg(media, payload=None, text="", file_name=None, chat_id=-100):
    return SimpleNamespace(
        id=42,
        chat=SimpleNamespace(id=chat_id, type=ChatType.SUPERGROUP),
        from_user=SimpleNamespace(id=1, first_name="u"),
        sender_chat=None,
        text=text,
        caption=None,
        entities=None,
        caption_entities=None,
        media=media,
        media_group_id=None,
        reply_to_message=None,
        reply_to_message_id=None,
        reply_to_top_message_id=None,
        photo=payload if media == MessageMediaType.PHOTO else None,
        video=payload if media == MessageMediaType.VIDEO else None,
        audio=payload if media == MessageMediaType.AUDIO else None,
        voice=payload if media == MessageMediaType.VOICE else None,
        document=payload if media == MessageMediaType.DOCUMENT else None,
        sticker=payload if media == MessageMediaType.STICKER else None,
        poll=payload if media == MessageMediaType.POLL else None,
        web_page=payload if media == MessageMediaType.WEB_PAGE else None,
        file_name=file_name,
    )


class _Client:
    def __init__(self, download=None):
        self._download = download

    async def download_media(self, *args, **kwargs):
        if self._download is None:
            raise AssertionError("download_media must not be called")
        return self._download

    @property
    def me(self):
        return None


async def test_unsupported_photo_leaves_placeholder(monkeypatch):
    monkeypatch.setattr(app_config, "agent_multimodal", False)
    msg = _media_msg(MessageMediaType.PHOTO, payload=SimpleNamespace(file_id="f"))
    prompts, needs_multimodal = await prompt.get_input_prompt(
        _Client(),
        msg,  # type: ignore[arg-type]
    )
    joined = " ".join(str(p) for p in prompts)
    assert "用户发送了图片" in joined
    assert "已省略" in joined
    assert needs_multimodal is False


async def test_unsupported_document_names_the_file(monkeypatch):
    monkeypatch.setattr(app_config, "agent_multimodal", False)
    doc = SimpleNamespace(file_id="f", file_name="report.pdf")
    msg = _media_msg(MessageMediaType.DOCUMENT, payload=doc)
    prompts, _ = await prompt.get_input_prompt(
        _Client(),
        msg,  # type: ignore[arg-type]
    )
    joined = " ".join(str(p) for p in prompts)
    assert "用户发送了文档《report.pdf》" in joined


async def test_plain_text_message_has_no_placeholder(monkeypatch):
    monkeypatch.setattr(app_config, "agent_multimodal", False)
    msg = _media_msg(None, text="hello")
    prompts, _ = await prompt.get_input_prompt(
        _Client(),
        msg,  # type: ignore[arg-type]
    )
    joined = " ".join(str(p) for p in prompts)
    assert "已省略" not in joined
    assert "hello" in joined


async def test_poll_is_text_represented_without_placeholder(monkeypatch):
    monkeypatch.setattr(app_config, "agent_multimodal", False)
    poll = SimpleNamespace(
        type=None,
        is_closed=False,
        total_voter_count=0,
        allows_multiple_answers=False,
        is_anonymous=True,
        question="q?",
        options=[SimpleNamespace(text="a", voter_count=0)],
        correct_option_ids=None,
        explanation=None,
    )
    msg = _media_msg(MessageMediaType.POLL, payload=poll)
    prompts, _ = await prompt.get_input_prompt(
        _Client(),
        msg,  # type: ignore[arg-type]
    )
    joined = " ".join(str(p) for p in prompts)
    assert "已省略" not in joined
    assert "q?" in joined


async def test_supported_photo_is_included_without_placeholder(monkeypatch):
    monkeypatch.setattr(app_config, "agent_multimodal", True)
    monkeypatch.setattr(app_config, "agent_multimodal_inputs", ["photo"])
    msg = _media_msg(MessageMediaType.PHOTO, payload=SimpleNamespace(file_id="f"))
    prompts, needs_multimodal = await prompt.get_input_prompt(
        _Client(download=BytesIO(b"image")),
        msg,  # type: ignore[arg-type]
    )
    joined = " ".join(str(p) for p in prompts)
    assert "已省略" not in joined
    assert needs_multimodal is True


async def test_oversize_video_leaves_placeholder(monkeypatch):
    monkeypatch.setattr(app_config, "agent_multimodal", True)
    monkeypatch.setattr(app_config, "agent_multimodal_inputs", ["video"])
    video = SimpleNamespace(
        file_id="f",
        mime_type="video/mp4",
        file_size=30 * 1024 * 1024,  # over the 20 MiB cap
    )
    msg = _media_msg(MessageMediaType.VIDEO, payload=video)
    prompts, _ = await prompt.get_input_prompt(
        _Client(),
        msg,  # type: ignore[arg-type]
    )
    joined = " ".join(str(p) for p in prompts)
    assert "用户发送了视频" in joined
