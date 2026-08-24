"""get_input_prompt media handling: unsupported media must leave a visible
placeholder so the model never answers as if the message had no media."""

from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace
from typing import cast

from pydantic_ai import Agent
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
            return BytesIO("这是文本文档内容".encode())
        return self._download

    @property
    def me(self):
        return None


async def _prompt(client, msg):
    """get_input_prompt with mocked client/message types."""
    return await prompt.get_input_prompt(client, msg)  # type: ignore[arg-type]


async def test_unsupported_photo_leaves_placeholder(monkeypatch):
    monkeypatch.setattr(app_config, "agent_multimodal", False)
    msg = _media_msg(MessageMediaType.PHOTO, payload=SimpleNamespace(file_id="f"))
    prompts, needs_multimodal = await _prompt(_Client(), msg)
    joined = " ".join(str(p) for p in prompts)
    assert "模型无法处理的内容: 图片" in joined
    assert needs_multimodal is False


async def test_unsupported_document_names_the_file(monkeypatch):
    monkeypatch.setattr(app_config, "agent_multimodal", False)
    doc = SimpleNamespace(
        file_id="f", file_name="report.pdf", file_size=1024, mime_type="application/pdf"
    )
    msg = _media_msg(MessageMediaType.DOCUMENT, payload=doc)
    prompts, _ = await _prompt(_Client(), msg)
    joined = " ".join(str(p) for p in prompts)
    assert "模型无法处理的内容: 文档《report.pdf》" in joined


async def test_plain_text_message_has_no_placeholder(monkeypatch):
    monkeypatch.setattr(app_config, "agent_multimodal", False)
    msg = _media_msg(None, text="hello")
    prompts, _ = await _prompt(_Client(), msg)
    joined = " ".join(str(p) for p in prompts)
    assert "模型无法处理" not in joined
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
    prompts, _ = await _prompt(_Client(), msg)
    joined = " ".join(str(p) for p in prompts)
    assert "模型无法处理" not in joined
    assert "q?" in joined


async def test_supported_photo_is_included_without_placeholder(monkeypatch):
    monkeypatch.setattr(app_config, "agent_multimodal", True)
    monkeypatch.setattr(app_config, "agent_multimodal_inputs", ["photo"])
    msg = _media_msg(MessageMediaType.PHOTO, payload=SimpleNamespace(file_id="f"))
    prompts, needs_multimodal = await _prompt(_Client(), msg)
    joined = " ".join(str(p) for p in prompts)
    assert "模型无法处理" not in joined
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
    prompts, _ = await _prompt(_Client(), msg)
    joined = " ".join(str(p) for p in prompts)
    assert "模型无法处理的内容: 视频" in joined


async def test_transcribe_replaces_media_with_description(monkeypatch):
    from pydantic_ai import BinaryContent
    from pydantic_ai.models.test import TestModel

    from kmua.plugins.agent import prompt as prompt_mod

    class _TranscribeModel(TestModel):
        def __init__(self):
            super().__init__(custom_output_text="图里有一只猫")

    prompt_mod.Agent = cast(
        type[Agent],
        lambda **kw: __import__("pydantic_ai").Agent(
            model=_TranscribeModel(), retries=2
        ),
    )
    try:
        result = await prompt_mod.transcribe_multimodal_content(
            object(),
            ["看这张图", BinaryContent(data=b"img", media_type="image/jpeg")],
        )
    finally:
        import pydantic_ai

        prompt_mod.Agent = pydantic_ai.Agent
    joined = " ".join(str(p) for p in result)
    assert "看这张图" in joined
    assert "图里有一只猫" in joined
    assert "BinaryContent" not in joined
    assert "转述" in joined


async def test_transcribe_no_media_returns_unchanged():
    from kmua.plugins.agent import prompt as prompt_mod

    result = await prompt_mod.transcribe_multimodal_content(object(), ["plain"])
    assert result == ["plain"]


async def test_transcribe_failure_falls_back_to_placeholder(monkeypatch):
    from pydantic_ai import BinaryContent
    from pydantic_ai.models.test import TestModel

    from kmua.plugins.agent import prompt as prompt_mod

    class _BoomModel(TestModel):
        async def request(self, *args, **kwargs):
            raise RuntimeError("model down")

    prompt_mod.Agent = cast(
        type[Agent],
        lambda **kw: __import__("pydantic_ai").Agent(model=_BoomModel(), retries=1),
    )
    try:
        result = await prompt_mod.transcribe_multimodal_content(
            object(),
            ["x", BinaryContent(data=b"i", media_type="image/jpeg")],
        )
    finally:
        import pydantic_ai

        prompt_mod.Agent = pydantic_ai.Agent
    joined = " ".join(str(p) for p in result)
    assert "转述失败" in joined
    assert "BinaryContent" not in joined


async def test_transcribe_uses_configured_instructions(monkeypatch):
    """The transcription instructions must come from config so operators can
    tune what the multimodal model reports."""
    from pydantic_ai import BinaryContent
    from pydantic_ai.models.test import TestModel

    from kmua.config import app_config
    from kmua.plugins.agent import prompt as prompt_mod

    captured = {}

    class _CaptureModel(TestModel):
        def __init__(self):
            super().__init__(custom_output_text="desc")

    real_agent = __import__("pydantic_ai").Agent

    def fake_agent(**kw):
        captured["instructions"] = kw.get("instructions")
        return real_agent(model=_CaptureModel(), retries=2)

    monkeypatch.setattr(
        app_config, "agent_multimodal_transcribe_prompt", "CUSTOM 转述要求"
    )
    prompt_mod.Agent = cast(type[Agent], fake_agent)
    try:
        await prompt_mod.transcribe_multimodal_content(
            object(),
            ["x", BinaryContent(data=b"i", media_type="image/jpeg")],
        )
    finally:
        import pydantic_ai

        prompt_mod.Agent = pydantic_ai.Agent
    assert captured["instructions"] == "CUSTOM 转述要求"


async def test_text_document_readable_without_multimodal(monkeypatch):
    """A plain-text document is readable even when multimodal is off: its
    content is text, not binary media."""
    monkeypatch.setattr(app_config, "agent_multimodal", False)
    doc = SimpleNamespace(
        file_id="f",
        file_name="notes.txt",
        file_size=1024,
        mime_type="text/plain; charset=utf-8",
    )
    msg = _media_msg(MessageMediaType.DOCUMENT, payload=doc)
    prompts, _ = await _prompt(_Client(), msg)
    joined = " ".join(str(p) for p in prompts)
    assert "这是文本文档内容" in joined
    assert "模型无法处理" not in joined


async def test_text_document_readable_without_multimodal_no_mime(monkeypatch):
    """mime_type is inferred from the file name when missing."""
    monkeypatch.setattr(app_config, "agent_multimodal", False)
    doc = SimpleNamespace(
        file_id="f", file_name="notes.md", file_size=1024, mime_type=None
    )
    msg = _media_msg(MessageMediaType.DOCUMENT, payload=doc)
    prompts, _ = await _prompt(_Client(), msg)
    joined = " ".join(str(p) for p in prompts)
    assert "这是文本文档内容" in joined
    assert "模型无法处理" not in joined
