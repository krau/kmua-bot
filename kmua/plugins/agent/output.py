import asyncio
from datetime import datetime

import pyrogram
import pyrogram.errors
from pyrogram.client import Client as PyrogramClient

from kmua.common.memory_store import memttlcache
from kmua.common.rich_message import send_rich_message
from kmua.config import app_config
from kmua.logger import logger
from kmua.plugins.agent import datatype, state
from kmua.plugins.agent.guest_mode import answer_guest_query
from kmua.plugins.agent.styling import (
    convert_md,
    convert_md_chunks,
    convert_rich_md,
)


async def _send_rich_payloads(
    client: PyrogramClient,
    message: pyrogram.types.Message,
    payloads: list[pyrogram.types.InputRichMessage],
) -> tuple[bool, int | None]:
    """Send converted rich payloads as replies to ``message``.

    Returns (sent, last message id); ``sent`` is False when nothing was
    delivered, so the caller can fall back to the plain entity path.
    """
    chat = message.chat
    if not payloads or chat is None or chat.id is None:
        return False, None
    chat_id = chat.id
    last_id: int | None = None
    for payload in payloads:
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
            return last_id is not None, last_id
    return True, last_id


async def _send_rich_reply(
    client: PyrogramClient,
    message: pyrogram.types.Message,
    markdown: str,
) -> tuple[bool, int | None]:
    """Convert markdown to rich payloads and send them as replies."""
    return await _send_rich_payloads(client, message, convert_rich_md(markdown))


async def _send_plain_reply(
    message: pyrogram.types.Message,
    markdown: str,
) -> tuple[pyrogram.types.Message | None, str]:
    """Send markdown as plain text + entities.

    Only splits when the converted text exceeds Telegram's per-message limit.
    Returns (last message, last delivered text).
    """
    last_msg: pyrogram.types.Message | None = None
    last_text = markdown
    for plain, entities in convert_md_chunks(markdown):
        try:
            last_msg = await message.reply_text(plain, entities=entities)
        except Exception as e:
            logger.warning(f"Send failed: {e.__class__.__name__} - {e}")
            last_msg = await message.reply_text(plain)
        if last_msg is not None and last_msg.text:
            last_text = last_msg.text
        else:
            last_text = plain
    return last_msg, last_text


async def reply_output(
    client: PyrogramClient,
    message: pyrogram.types.Message,
    text: str,
    deps: "datatype.ContextDeps | None" = None,
):
    if message.guest_query_id:
        return await answer_guest_query(client, message, text, deps=deps)
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
        sent = False
        if app_config.agent_rich_output:
            sent, last_reply_id = await _send_rich_reply(client, message, text)
            if sent:
                last_reply_text = text
        if not sent:
            last_reply_msg, last_reply_text = await _send_plain_reply(message, text)
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
                original_user_message=message.text or message.caption or "",
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
        deps: "datatype.ContextDeps | None" = None,
    ):
        self.client = client
        self.message = message
        self.deps = deps
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
        self.is_guest = bool(message.guest_query_id)

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
        self._rich = bool(app_config.agent_rich_output)
        if self._rich:
            sent, message_id = await _send_rich_reply(self.client, self.message, text)
            if sent:
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
        if self.is_guest:
            return
        await self._send_new_message(self.current_text)
        self._edit_task = asyncio.create_task(self._edit_loop())

    async def append_delta(self, delta: str):
        if not delta:
            return
        self.current_text += delta
        if self.is_guest:
            return
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
            return
        # Long answers are split at Telegram's rich message limits; the
        # overflow goes out as follow-up rich messages.
        if len(payloads) > 1:
            await _send_rich_payloads(self.client, self.message, payloads[1:])

    async def finalize(self):
        self._stop = True
        if self.is_guest:
            if self.current_text:
                from kmua.plugins.agent.guest_mode import answer_guest_query

                await answer_guest_query(
                    self.client, self.message, self.current_text, deps=self.deps
                )
            return
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
                original_user_message=self.message.text or self.message.caption or "",
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
