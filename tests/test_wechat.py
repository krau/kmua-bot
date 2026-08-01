"""WeChat article parsing tests — services layer (pure functions) plus the
plugin wiring with network and Telegram calls stubbed.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from kmua.plugins import wechat as wechat_plugin
from kmua.services import wechat as wechat_service

# A minimal article page: title, author, publish time, three images.
_ARTICLE_HTML = """
<html><head>
<meta property="og:title" content="测试文章标题">
<meta property="og:description" content="这是一段描述">
</head><body>
<div id="js_name">测试公众号</div>
<div id="publish_time">2026-07-20 10:30</div>
<div id="js_content">
<section><p>第一段正文内容。</p></section>
<section><p>第二段正文内容, 更详细一点。</p></section>
<img data-src="https://mmbiz.qpic.cn/mmbiz_jpg/aaa">
<img src="https://mmbiz.qpic.cn/mmbiz_png/bbb">
<img src="https://evil.example.com/x.jpg">
</div>
</body></html>
"""

# A share-card/verify page with no body: must fall back to og:description.
_SHARE_HTML = """
<html><head>
<meta property="og:title" content="摘要页标题">
<meta property="og:description" content="正文摘要文本, 无法获取全文。">
</head><body><div id="js_name"></div></body></html>
"""

ARTICLE_URL = "https://mp.weixin.qq.com/s/testid123"


# ------------------------------------------------------------------ url checks


def test_is_wechat_url_accepts_article_links():
    assert wechat_service.is_wechat_url("https://mp.weixin.qq.com/s/abc123")
    assert wechat_service.is_wechat_url("https://mp.weixin.qq.com/s/a-b_c")


def test_is_wechat_url_rejects_lookalikes():
    assert not wechat_service.is_wechat_url("https://evil.com/s/abc123")
    assert not wechat_service.is_wechat_url("https://mp.weixin.qq.com@evil.com/s/abc")
    assert not wechat_service.is_wechat_url("https://mp.weixin.qq.com/other/abc")
    assert not wechat_service.is_wechat_url("http://mp.weixin.qq.com/s/abc")  # http


# ------------------------------------------------------------------ parsing


def test_parse_article_html_extracts_all_fields():
    article = wechat_service.parse_article_html(_ARTICLE_HTML, ARTICLE_URL)
    assert article.title == "测试文章标题"
    assert article.author == "测试公众号"
    assert article.published_at is not None
    assert article.published_at.year == 2026
    assert article.paragraphs[0] == "第一段正文内容。"
    # The evil-domain image is rejected, the two mmbiz ones kept.
    assert len(article.images) == 2
    assert all("mmbiz.qpic.cn" in u for u in article.images)


def test_parse_article_html_falls_back_to_description():
    article = wechat_service.parse_article_html(_SHARE_HTML, ARTICLE_URL)
    assert article.title == "摘要页标题"
    assert article.author is None
    assert article.paragraphs == ["正文摘要文本, 无法获取全文。"]
    assert article.images == []


def test_download_image_rejects_extreme_aspect_ratio():
    """Telegram rejects >20:1 photos; such WeChat strips must be dropped."""
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (844, 18), color="red").save(buf, format="JPEG")

    async def fake_get(url):
        async def fake_aread():
            return buf.getvalue()

        return SimpleNamespace(
            raise_for_status=lambda: None,
            aread=fake_aread,
        )

    fake_client = SimpleNamespace(get=fake_get)

    async def run():
        try:
            await wechat_service.download_image(fake_client, "https://mmbiz.qpic.cn/1")
            return None
        except ValueError as e:
            return str(e)

    result = asyncio.run(run())
    assert result and "aspect ratio" in result


async def test_download_image_converts_to_jpeg():
    """Non-JPEG uploads are re-encoded; WeChat PNGs may be rejected otherwise."""
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGBA", (100, 50), color="blue").save(buf, format="PNG")

    async def fake_get(url):
        async def fake_aread():
            return buf.getvalue()

        return SimpleNamespace(
            raise_for_status=lambda: None,
            aread=fake_aread,
        )

    fake_client = SimpleNamespace(get=fake_get)
    data = await wechat_service.download_image(fake_client, "https://mmbiz.qpic.cn/1")
    with Image.open(io.BytesIO(data)) as im:
        assert im.format == "JPEG"


def test_parse_article_html_limits_images():
    many_imgs = "".join(
        f'<img data-src="https://mmbiz.qpic.cn/mmbiz_jpg/{i}">' for i in range(15)
    )
    html = f'<html><body><div id="js_content">{many_imgs}</div></body></html>'
    article = wechat_service.parse_article_html(html, ARTICLE_URL)
    assert len(article.images) == 10


# ------------------------------------------------------------------ formatting


def test_build_rich_blocks_interleaves_images_and_quotes():
    from pyrogram.raw.types.page_block_blockquote import PageBlockBlockquote
    from pyrogram.raw.types.page_block_heading1 import PageBlockHeading1
    from pyrogram.raw.types.page_block_photo import PageBlockPhoto

    article = wechat_service.WechatArticle(
        url=ARTICLE_URL,
        title="标题",
        author="作者",
        blocks=[
            wechat_service.WechatBlock(kind="text", content="第一段"),
            wechat_service.WechatBlock(kind="image", content="https://mmbiz.qpic.cn/1"),
            wechat_service.WechatBlock(kind="text", content="第二段"),
        ],
    )
    # Without photo ids the image block is dropped.
    blocks = wechat_service.build_rich_blocks(article, lang="zh-CN")
    assert not any(isinstance(b, PageBlockPhoto) for b in blocks)
    assert isinstance(blocks[0], PageBlockHeading1)
    assert any(isinstance(b, PageBlockBlockquote) for b in blocks)

    # With a photo id the image is interleaved at its document position.
    class FakePhotoRef:
        id = 42

    blocks2 = wechat_service.build_rich_blocks(
        article, lang="zh-CN", photo_refs=[FakePhotoRef()]
    )
    kinds = [type(b).__name__ for b in blocks2]
    assert "PageBlockPhoto" in kinds
    photo_idx = kinds.index("PageBlockPhoto")
    assert kinds[photo_idx - 1] == "PageBlockBlockquote"  # text before image
    assert kinds[photo_idx + 1] == "PageBlockBlockquote"  # text after image
    assert blocks2[photo_idx].photo_id == 42

    # Consecutive paragraphs share one block quote, separated by blank lines.
    from pyrogram.raw.types.text_plain import TextPlain

    article3 = wechat_service.WechatArticle(
        url=ARTICLE_URL,
        blocks=[
            wechat_service.WechatBlock(kind="text", content="第一段"),
            wechat_service.WechatBlock(kind="text", content="第二段"),
            wechat_service.WechatBlock(kind="text", content="第三段"),
        ],
    )
    blocks3 = wechat_service.build_rich_blocks(article3, lang="zh-CN")
    quotes = [b for b in blocks3 if isinstance(b, PageBlockBlockquote)]
    assert len(quotes) == 1
    assert quotes[0].text.text == "第一段\n\n第二段\n\n第三段"


def test_build_media_caption_truncates_to_1024():
    article = wechat_service.WechatArticle(
        url=ARTICLE_URL,
        title="标题" * 400,  # long title pushes the caption past 1024
        paragraphs=["很长的正文" * 500],
    )
    caption = wechat_service.build_media_caption(article, lang="zh-CN")
    assert len(caption) <= 1024
    assert caption.endswith("…")


# ------------------------------------------------------------- plugin wiring


@pytest.fixture
def fake_message():
    import pyrogram

    class FakeReply:
        def __init__(self):
            self.media_groups = []
            self.texts = []

        async def reply_media_group(self, inputs, **kwargs):
            self.media_groups.append((inputs, kwargs))
            return []

        async def reply_text(self, text, **kwargs):
            self.texts.append((text, kwargs))

        async def reply_chat_action(self, action):
            pass

    chat = pyrogram.types.Chat(
        id=-100_123456789, type=pyrogram.enums.ChatType.SUPERGROUP, title="测试群"
    )
    user = pyrogram.types.User(id=1001, first_name="Tester")
    return chat, user, FakeReply()


def _make_message(fake_message, url):
    import pyrogram

    chat, user, reply = fake_message
    message = pyrogram.types.Message(
        id=1,
        chat=chat,
        from_user=user,
        text=url,
        service=False,
        outgoing=False,
    )
    message.matches = [type("M", (), {"group": lambda self: url})()]
    message.reply_text = reply.reply_text
    message.reply_media_group = reply.reply_media_group
    message.reply_chat_action = reply.reply_chat_action
    return message


async def test_plugin_ignores_non_wechat_text(fake_message, monkeypatch):
    from kmua.database.models import ChatConfig

    async def fake_get_chat_config(chat_id):
        return ChatConfig(parse_wechat_enabled=True)

    monkeypatch.setattr("kmua.database.get_chat_config", fake_get_chat_config)

    called = []

    async def fake_fetch(url):
        called.append(url)
        raise AssertionError("should not be called")

    monkeypatch.setattr(wechat_service, "fetch_article", fake_fetch)
    chat, user, reply = fake_message
    message = _make_message(fake_message, "https://example.com/not-wechat")
    await wechat_plugin.parse_wechat_article(None, message)
    assert called == []


async def test_plugin_disabled_by_chat_config(fake_message, monkeypatch):
    from kmua.database.models import ChatConfig

    async def fake_get_chat_config(chat_id):
        return ChatConfig(parse_wechat_enabled=False)

    monkeypatch.setattr("kmua.database.get_chat_config", fake_get_chat_config)

    called = []

    async def fake_fetch(url):
        called.append(url)

    monkeypatch.setattr(wechat_service, "fetch_article", fake_fetch)
    message = _make_message(fake_message, "https://mp.weixin.qq.com/s/abc123")
    await wechat_plugin.parse_wechat_article(None, message)
    assert called == []


async def test_plugin_text_send_for_image_free_article(fake_message, monkeypatch):
    from kmua.database.models import ChatConfig

    async def fake_get_chat_config(chat_id):
        return ChatConfig(parse_wechat_enabled=True)

    monkeypatch.setattr("kmua.database.get_chat_config", fake_get_chat_config)

    article = wechat_service.WechatArticle(
        url="https://mp.weixin.qq.com/s/abc123",
        title="标题",
        author="作者",
        paragraphs=["正文"],
    )

    async def fake_fetch(url):
        return article

    rich_calls = []

    async def fake_resolve_peer(chat_id):
        return SimpleNamespace(user_id=chat_id)

    async def fake_invoke(query, **kwargs):
        rich_calls.append(query.rich_message)

    fake_client = SimpleNamespace(
        resolve_peer=fake_resolve_peer,
        invoke=fake_invoke,
        rnd_id=lambda: 1,
    )
    monkeypatch.setattr(wechat_service, "fetch_article", fake_fetch)
    message = _make_message(fake_message, "https://mp.weixin.qq.com/s/abc123")
    await wechat_plugin.parse_wechat_article(fake_client, message)

    assert len(rich_calls) == 1
    from pyrogram.raw.types.page_block_heading1 import PageBlockHeading1

    assert any(isinstance(b, PageBlockHeading1) for b in rich_calls[0].blocks)


async def test_plugin_media_group_send(fake_message, monkeypatch):
    from kmua.database.models import ChatConfig

    async def fake_get_chat_config(chat_id):
        return ChatConfig(parse_wechat_enabled=True)

    monkeypatch.setattr("kmua.database.get_chat_config", fake_get_chat_config)

    article = wechat_service.WechatArticle(
        url="https://mp.weixin.qq.com/s/abc123",
        title="图文标题",
        author="作者",
        paragraphs=["正文"],
        images=["https://mmbiz.qpic.cn/1", "https://mmbiz.qpic.cn/2"],
        blocks=[
            wechat_service.WechatBlock(kind="text", content="正文"),
            wechat_service.WechatBlock(kind="image", content="https://mmbiz.qpic.cn/1"),
            wechat_service.WechatBlock(kind="image", content="https://mmbiz.qpic.cn/2"),
        ],
    )

    async def fake_fetch(url):
        return article

    async def fake_download(client, url):
        return b"fake-image-bytes"

    from pyrogram.raw.functions.messages.upload_media import UploadMedia
    from pyrogram.raw.types.input_photo import InputPhoto
    from pyrogram.raw.types.page_block_photo import PageBlockPhoto

    rich_calls = []
    upload_calls = []

    class FakePhoto:
        id = 777
        access_hash = 888
        file_reference = b"fr"

    async def fake_resolve_peer(chat_id):
        return SimpleNamespace(user_id=chat_id)

    async def fake_save_file(data):
        return SimpleNamespace()

    async def fake_invoke(query, **kwargs):
        if isinstance(query, UploadMedia):
            upload_calls.append(1)
            return SimpleNamespace(photo=FakePhoto())
        rich_calls.append(query.rich_message)

    fake_client = SimpleNamespace(
        resolve_peer=fake_resolve_peer,
        invoke=fake_invoke,
        save_file=fake_save_file,
        rnd_id=lambda: 1,
    )
    monkeypatch.setattr(wechat_service, "fetch_article", fake_fetch)
    monkeypatch.setattr(wechat_service, "download_image", fake_download)
    message = _make_message(fake_message, "https://mp.weixin.qq.com/s/abc123")
    await wechat_plugin.parse_wechat_article(fake_client, message)

    # both images uploaded, then one rich message carrying them inline
    assert len(upload_calls) == 2
    assert len(rich_calls) == 1
    rich = rich_calls[0]
    assert rich.photos and isinstance(rich.photos[0], InputPhoto)
    assert rich.photos[0].id == 777
    photo_blocks = [b for b in rich.blocks if isinstance(b, PageBlockPhoto)]
    assert len(photo_blocks) == 2
    assert all(b.photo_id == 777 for b in photo_blocks)


async def test_plugin_falls_back_to_text_when_images_fail(fake_message, monkeypatch):
    from kmua.database.models import ChatConfig

    async def fake_get_chat_config(chat_id):
        return ChatConfig(parse_wechat_enabled=True)

    monkeypatch.setattr("kmua.database.get_chat_config", fake_get_chat_config)

    article = wechat_service.WechatArticle(
        url="https://mp.weixin.qq.com/s/abc123",
        title="标题",
        paragraphs=["正文"],
        images=["https://mmbiz.qpic.cn/1"],
        blocks=[
            wechat_service.WechatBlock(kind="text", content="正文"),
            wechat_service.WechatBlock(kind="image", content="https://mmbiz.qpic.cn/1"),
        ],
    )

    async def fake_fetch(url):
        return article

    async def fake_download(client, url):
        return b"fake-image-bytes"

    media_calls = []

    async def fake_send_media_group(chat_id, media, **kwargs):
        media_calls.append(media)

    async def fake_resolve_peer(chat_id):
        return SimpleNamespace(user_id=chat_id)

    async def fake_save_file(data):
        return SimpleNamespace()

    async def fake_invoke(query, **kwargs):
        raise RuntimeError("rich send broken")

    fake_client = SimpleNamespace(
        send_media_group=fake_send_media_group,
        resolve_peer=fake_resolve_peer,
        invoke=fake_invoke,
        save_file=fake_save_file,
        rnd_id=lambda: 1,
    )
    monkeypatch.setattr(wechat_service, "fetch_article", fake_fetch)
    monkeypatch.setattr(wechat_service, "download_image", fake_download)
    message = _make_message(fake_message, "https://mp.weixin.qq.com/s/abc123")
    await wechat_plugin.parse_wechat_article(fake_client, message)

    # rich upload/send failed: fell back to the media group
    assert len(media_calls) == 1
