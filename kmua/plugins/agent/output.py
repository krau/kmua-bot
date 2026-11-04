import asyncio
from datetime import datetime

import pyrogram
from pyrogram.client import Client as PyrogramClient

from kmua.common.memory_store import memttlcache
from kmua.common.rich_message import (
    message_plain_text,
    rich_html_plain_text,
    send_rich_message,
)
from kmua.common.utils import GROUP_CHAT_TYPES
from kmua.config import app_config
from kmua.logger import logger
from kmua.plugins.agent import datatype, state
from kmua.plugins.agent.styling import (
    convert_md_chunks,
    convert_rich_md,
    split_plain_text,
)

# A rich send that keeps failing (unsupported client, server-side outage) is
# paused for a while: every attempt otherwise costs a failed request before
# the plain fallback.
_RICH_FAILURE_LIMIT = 3
_RICH_FAILURE_TTL = 300
_RICH_FAILURE_KEY = "agent_rich_failures"
_RICH_DISABLED_KEY = "agent_rich_disabled"


async def _rich_output_enabled() -> bool:
    if not app_config.agent_rich_output:
        return False
    return not await memttlcache.get(_RICH_DISABLED_KEY, False)


async def _note_rich_result(sent: bool) -> None:
    if sent:
        await memttlcache.delete(_RICH_FAILURE_KEY)
        await memttlcache.delete(_RICH_DISABLED_KEY)
        return
    failures = int(await memttlcache.get(_RICH_FAILURE_KEY, 0) or 0) + 1
    await memttlcache.set(_RICH_FAILURE_KEY, failures, ttl=_RICH_FAILURE_TTL)
    if failures >= _RICH_FAILURE_LIMIT:
        logger.warning(
            f"Rich message output paused for {_RICH_FAILURE_TTL}s after "
            f"{failures} consecutive send failures"
        )
        await memttlcache.set(_RICH_DISABLED_KEY, True, ttl=_RICH_FAILURE_TTL)


async def _send_rich_payloads(
    client: PyrogramClient,
    message: pyrogram.types.Message,
    payloads: list[pyrogram.types.InputRichMessage],
) -> tuple[int, int | None]:
    """Send rich payloads in order, stopping at the first failure.

    Returns (delivered count, last delivered message id); callers deliver the
    undelivered tail through the plain text path.
    """
    chat = message.chat
    if not payloads or chat is None or chat.id is None:
        return 0, None
    chat_id = chat.id
    last_id: int | None = None
    for index, payload in enumerate(payloads):
        try:
            last_id = await send_rich_message(
                client,
                chat_id,
                payload.write(),
                reply_parameters=pyrogram.types.ReplyParameters(message_id=message.id),
                message_thread_id=message.message_thread_id,
                direct_messages_topic_id=message.direct_messages_topic_id,
            )
        except Exception as e:
            logger.warning(f"Rich message send failed: {e.__class__.__name__} - {e}")
            await _note_rich_result(False)
            return index, last_id
    await _note_rich_result(True)
    return len(payloads), last_id


async def _send_rich_tail_plain(
    message: pyrogram.types.Message,
    payloads: list[pyrogram.types.InputRichMessage],
) -> None:
    text = "\n\n".join(
        part
        for part in (
            rich_html_plain_text(payload.html or payload.markdown or "")
            for payload in payloads
        )
        if part
    )
    if not text:
        return
    for chunk in split_plain_text(text):
        try:
            await message.reply_text(chunk)
        except Exception as e:
            logger.error(
                f"Failed to send rich fallback text: {e.__class__.__name__} - {e}"
            )
            return


async def _send_plain_reply(
    message: pyrogram.types.Message,
    markdown: str,
) -> pyrogram.types.Message | None:
    """Send markdown as plain text + entities.

    Only splits when the converted text exceeds Telegram's per-message limit;
    a chunk that fails twice is skipped so later chunks still go out. Returns
    the last delivered message, and raises when nothing could be delivered.
    """
    last_msg: pyrogram.types.Message | None = None
    last_error: Exception | None = None
    for plain, entities in convert_md_chunks(markdown):
        try:
            last_msg = await message.reply_text(plain, entities=entities)
            last_error = None
        except Exception as e:
            logger.warning(f"Send failed: {e.__class__.__name__} - {e}")
            try:
                last_msg = await message.reply_text(plain)
                last_error = None
            except Exception as e:
                logger.error(f"Send failed: {e.__class__.__name__} - {e}")
                last_error = e
    if last_msg is None and last_error is not None:
        raise last_error
    return last_msg


async def reply_output(
    client: PyrogramClient,
    message: pyrogram.types.Message,
    text: str,
):
    if message.chat is None:
        return
    is_group_chat = message.chat.type in GROUP_CHAT_TYPES
    user = message.sender_chat or message.from_user
    if not text.strip():
        return
    try:
        last_reply_id: int | None = None
        last_reply_msg: pyrogram.types.Message | None = None
        last_reply_text = ""
        if await _rich_output_enabled():
            payloads = convert_rich_md(text)
            sent_count, last_reply_id = await _send_rich_payloads(
                client, message, payloads
            )
            if sent_count:
                last_reply_text = text
            if 0 < sent_count < len(payloads):
                await _send_rich_tail_plain(message, payloads[sent_count:])
        if not last_reply_text:
            last_reply_msg = await _send_plain_reply(message, text)
            last_reply_text = text
        last_reply_message_id = last_reply_id or (
            last_reply_msg.id if last_reply_msg else None
        )
        if (
            last_reply_message_id
            and last_reply_text
            and is_group_chat
            and user
            and user.id
        ):
            bot_reply = datatype.BotLastReply(
                message_id=last_reply_message_id,
                reply_to_user_id=user.id,
                reply_to_message_id=message.id,
                reply_text=last_reply_text,
                original_user_message=message_plain_text(message),
                timestamp=datetime.now().timestamp(),
            )
            _chat = message.chat
            _chat_id = _chat.id if _chat else None
            if _chat_id:
                await memttlcache.set(
                    state.bot_last_reply_key(_chat_id),
                    bot_reply,
                    ttl=300,
                )
    except Exception as e:
        logger.error(f"Error replying message: {e.__class__.__name__} - {e}")


class TypingKeepAlive:
    """Standalone context manager that keeps the TYPING action going
    independently of the agent run, so typing continues during tool calls too.
    """

    CHAT_ACTION_INTERVAL = 4

    def __init__(self, client: PyrogramClient, message: pyrogram.types.Message):
        self.client = client
        self.message = message
        self._stop = False
        self._task: asyncio.Task | None = None

    async def _loop(self):
        chat = self.message.chat
        chat_id = chat.id if chat else None
        if not chat_id:
            return
        first = True
        while not self._stop:
            try:
                if not first:
                    await asyncio.sleep(self.CHAT_ACTION_INTERVAL)
                    if self._stop:
                        break
                first = False
                await self.client.send_chat_action(
                    chat_id=chat_id,
                    action=pyrogram.enums.ChatAction.TYPING,
                )
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"TypingKeepAlive: error sending chat action: {e}")
                break

    def start(self):
        self._stop = False
        self._task = asyncio.create_task(self._loop())

    async def stop(self):
        self._stop = True
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def __aenter__(self):
        self.start()
        return self

    async def __aexit__(self, *_):
        await self.stop()
