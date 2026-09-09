import asyncio
from datetime import datetime

import pyrogram
import pyrogram.errors
from pyrogram.client import Client as PyrogramClient

from kmua.common.memory_store import memttlcache
from kmua.common.rich_message import (
    message_plain_text,
    rich_html_plain_text,
    send_rich_message,
)
from kmua.config import app_config
from kmua.logger import logger
from kmua.plugins.agent import datatype, state
from kmua.plugins.agent.styling import (
    convert_md,
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
    """Track consecutive rich send failures for the circuit breaker."""
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
    """Deliver rich payloads that could not be sent as rich, as plain text."""
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
    is_group_chat = message.chat.type in (
        pyrogram.enums.ChatType.SUPERGROUP,
        pyrogram.enums.ChatType.GROUP,
    )
    user = message.sender_chat or message.from_user
    if not text.strip():
        return
    try:
        last_reply_id: int | None = None
        last_reply_msg: pyrogram.types.Message | None = None
        last_reply_text = ""
        # One message per answer on purpose: the old paragraph chunking (up to
        # 7 messages with random delays) is gone, only Telegram's per-message
        # limits split the output now.
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
    """Maintains a typing chat action for the duration of a long-running operation.

    This is a standalone context manager that keeps sending TYPING status
    independently of StreamingOutput, so typing continues during tool calls too.
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


class StreamingOutput:
    STREAM_EDIT_INTERVAL = 1.5
    MAX_MESSAGE_LENGTH = 4000
    MAX_EDIT_COUNT = 20
    MAX_TOTAL_TIME = float(app_config.agent_streaming_max_time)

    def __init__(
        self,
        client: PyrogramClient,
        message: pyrogram.types.Message,
    ):
        self.client = client
        self.message = message
        self.current_text = ""
        self._last_sent_text = ""
        self.reply_message_id: int | None = None
        self._rich = False
        self.last_edit_time = 0.0
        self.edit_count = 0
        self.start_time = 0.0
        self.is_group_chat = message.chat and message.chat.type in (
            pyrogram.enums.ChatType.SUPERGROUP,
            pyrogram.enums.ChatType.GROUP,
        )
        self.user = message.sender_chat or message.from_user
        self._edit_task: asyncio.Task | None = None
        self._start_task: asyncio.Task | None = None
        self._stop = False

    def _is_within_limits(self) -> bool:
        current_time = asyncio.get_event_loop().time()
        if self.start_time == 0.0:
            self.start_time = current_time
        elapsed = current_time - self.start_time
        if elapsed > self.MAX_TOTAL_TIME:
            logger.warning(f"Streaming output exceeded max time {self.MAX_TOTAL_TIME}s")
            return False
        if self.edit_count >= self.MAX_EDIT_COUNT:
            logger.warning(
                f"Streaming output exceeded max edit count {self.MAX_EDIT_COUNT}"
            )
            return False
        return True

    async def _do_edit(self, text: str):
        chat = self.message.chat
        if self.reply_message_id is None or chat is None or chat.id is None:
            return
        chat_id = chat.id
        try:
            if self._rich:
                payloads = convert_rich_md(text)
                if not payloads:
                    return
                await self.client.edit_message_text(
                    chat_id,
                    self.reply_message_id,
                    rich_message=payloads[0],
                )
            else:
                # During streaming, send plain text without entities to avoid
                # rendering partially-formed markdown. Entities applied at finalize.
                await self.client.edit_message_text(
                    chat_id,
                    self.reply_message_id,
                    text[: self.MAX_MESSAGE_LENGTH],
                    parse_mode=pyrogram.enums.ParseMode.DISABLED,
                )
            self._last_sent_text = text
            self.last_edit_time = asyncio.get_event_loop().time()
            self.edit_count += 1
        except pyrogram.errors.exceptions.bad_request_400.MessageNotModified:
            self._last_sent_text = text
        except pyrogram.errors.exceptions.bad_request_400.MessageTooLong:
            await self._send_new_message(text)
        except Exception as e:
            logger.error(f"Error editing message: {e.__class__.__name__} - {e}")

    async def _send_new_message(self, text: str):
        self._rich = await _rich_output_enabled()
        if self._rich:
            # Only the first payload opens the stream; the overflow of a
            # >32768-byte answer goes out once at finalize instead of being
            # sent twice.
            payloads = convert_rich_md(text)[:1]
            sent_count, message_id = await _send_rich_payloads(
                self.client, self.message, payloads
            )
            if sent_count:
                if message_id is None:
                    # Without the id the stream can neither edit nor finalize.
                    raise RuntimeError("Rich streaming reply message was not returned")
                self.reply_message_id = message_id
                self._last_sent_text = text
                self.last_edit_time = asyncio.get_event_loop().time()
                self.edit_count += 1
                return
            self._rich = False
        plain, entities = convert_md(text)
        try:
            reply_message = await self.message.reply_text(
                plain[: self.MAX_MESSAGE_LENGTH],
                entities=entities,
            )
        except Exception as e:
            logger.error(f"Send failed in streaming: {e}")
            raise
        if reply_message is None or reply_message.id is None:
            raise RuntimeError("Streaming reply message was not returned")
        self.reply_message_id = reply_message.id
        self._last_sent_text = text
        self.last_edit_time = asyncio.get_event_loop().time()
        self.edit_count += 1

    async def _edit_loop(self):
        while not self._stop:
            await asyncio.sleep(self.STREAM_EDIT_INTERVAL)
            if self._stop:
                break
            if not self._is_within_limits():
                break
            text = self.current_text
            if not text.strip() or text == self._last_sent_text:
                continue
            await self._do_edit(text)

    async def _start(self):
        await self._send_new_message(self.current_text)
        self._edit_task = asyncio.create_task(self._edit_loop())

    async def append_delta(self, delta: str):
        if not delta:
            return
        self.current_text += delta
        if self.start_time == 0.0 and self.current_text.strip():
            self.start_time = asyncio.get_event_loop().time()
            self._stop = False
            self._start_task = asyncio.create_task(self._start())

    async def _finalize_rich(self, text: str) -> None:
        chat = self.message.chat
        if chat is None or chat.id is None or self.reply_message_id is None:
            return
        chat_id = chat.id
        payloads = convert_rich_md(text)
        if not payloads:
            return
        try:
            await self.client.edit_message_text(
                chat_id,
                self.reply_message_id,
                rich_message=payloads[0],
            )
            self._last_sent_text = text
        except pyrogram.errors.exceptions.bad_request_400.MessageNotModified:
            pass
        except Exception as e:
            logger.error(f"Error editing final message: {e.__class__.__name__} - {e}")
        # Long answers are split at Telegram's rich message limits; the
        # overflow goes out even when the final edit failed, so no content is
        # dropped.
        if len(payloads) > 1:
            sent_count, _ = await _send_rich_payloads(
                self.client, self.message, payloads[1:]
            )
            if sent_count < len(payloads) - 1:
                await _send_rich_tail_plain(self.message, payloads[1 + sent_count :])

    async def finalize(self):
        self._stop = True
        if self._start_task and not self._start_task.done():
            await self._start_task
        if self._edit_task and not self._edit_task.done():
            self._edit_task.cancel()
            try:
                await self._edit_task
            except asyncio.CancelledError:
                pass
        chat = self.message.chat
        if (
            self.reply_message_id is not None
            and chat is not None
            and chat.id is not None
            and self.current_text
        ):
            chat_id = chat.id
            text = self.current_text
            if self._rich:
                await self._finalize_rich(text)
            else:
                plain, entities = convert_md(text)
                if text != self._last_sent_text or entities:
                    try:
                        await self.client.edit_message_text(
                            chat_id,
                            self.reply_message_id,
                            plain[: self.MAX_MESSAGE_LENGTH],
                            entities=entities,
                        )
                        self._last_sent_text = text
                    except (
                        pyrogram.errors.exceptions.bad_request_400.MessageNotModified
                    ):
                        pass
                    except Exception as e:
                        logger.error(f"Error editing final message: {e}")
        if self.reply_message_id and self.is_group_chat and self.user and self.user.id:
            bot_reply = datatype.BotLastReply(
                message_id=self.reply_message_id,
                reply_to_user_id=self.user.id,
                reply_to_message_id=self.message.id,
                reply_text=self.current_text,
                original_user_message=message_plain_text(self.message),
                timestamp=datetime.now().timestamp(),
            )
            chat = self.message.chat
            chat_id = chat.id if chat else None
            if chat_id:
                await memttlcache.set(
                    state.bot_last_reply_key(chat_id),
                    bot_reply,
                    ttl=300,
                )

    async def abort(self):
        self._stop = True
        for task in (self._start_task, self._edit_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
