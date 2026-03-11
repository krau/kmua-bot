import asyncio
import random
from datetime import datetime

import pyrogram
import pyrogram.errors
from pyrogram.client import Client as PyrogramClient

from kmua.common.memory_store import memttlcache
from kmua.logger import logger
from kmua.plugins.agent import datatype, state
from kmua.plugins.agent.styling import convert_md


async def reply_output(
    client: PyrogramClient, message: pyrogram.types.Message, text: str
):
    if message.chat is None:
        return
    is_group_chat = message.chat.type in (
        pyrogram.enums.ChatType.SUPERGROUP,
        pyrogram.enums.ChatType.GROUP,
    )
    user = message.sender_chat or message.from_user
    lines = [line for line in text.split("\n\n") if line.strip()]
    if not lines:
        return
    total_plain, total_entities = convert_md(text)
    has_block = False
    for e in total_entities:
        if (
            e.type == pyrogram.enums.MessageEntityType.BLOCKQUOTE
            or e.type == pyrogram.enums.MessageEntityType.PRE
        ):
            has_block = True
            break

    max_messages = 7
    total_sentences = len(lines)
    num_messages = min(max_messages, total_sentences)

    base = total_sentences // num_messages
    remainder = total_sentences % num_messages

    chunks: list[str] = []
    index = 0
    for i in range(num_messages):
        size = base + (1 if i < remainder else 0)
        part = lines[index : index + size]
        index += size
        chunks.append("\n".join(part))
    try:
        last_reply_msg: pyrogram.types.Message | None = None
        if has_block:
            last_reply_msg = await message.reply_text(
                total_plain, entities=total_entities
            )
        else:
            for chunk in chunks:
                await message.reply_chat_action(pyrogram.enums.ChatAction.TYPING)

                plain_chunk, entities = convert_md(chunk)
                try:
                    reply_msg = await message.reply_text(plain_chunk, entities=entities)
                except Exception as e:
                    logger.warning(f"Send failed: {e.__class__.__name__} - {e}")
                    try:
                        reply_msg = await message.reply_text(plain_chunk)
                    except Exception as e:
                        logger.error(f"Send failed: {e.__class__.__name__} - {e}")
                        raise
                last_reply_msg = reply_msg
                await asyncio.sleep(random.uniform(0.721, 3.9) + len(chunk) / 600)
        if (
            last_reply_msg
            and last_reply_msg.text
            and is_group_chat
            and user
            and user.id
        ):
            bot_reply = datatype.BotLastReply(
                message_id=last_reply_msg.id,
                reply_to_user_id=user.id,
                reply_to_message_id=message.id,
                reply_text=last_reply_msg.text,
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
    MAX_TOTAL_TIME = 120.0

    def __init__(
        self,
        client: PyrogramClient,
        message: pyrogram.types.Message,
    ):
        self.client = client
        self.message = message
        self.current_text = ""
        self._last_sent_text = ""
        self.reply_message: pyrogram.types.Message | None = None
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
        if not self.reply_message:
            return
        try:
            # During streaming, send plain text without entities to avoid
            # rendering partially-formed markdown. Entities applied at finalize.
            await self.reply_message.edit_text(
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
        plain, entities = convert_md(text)
        try:
            self.reply_message = await self.message.reply_text(
                plain[: self.MAX_MESSAGE_LENGTH],
                entities=entities,
            )
        except Exception as e:
            logger.error(f"Send failed in streaming: {e}")
            raise
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
        if self.reply_message and self.current_text:
            text = self.current_text
            plain, entities = convert_md(text)
            if text != self._last_sent_text or entities:
                try:
                    await self.reply_message.edit_text(
                        plain[: self.MAX_MESSAGE_LENGTH],
                        entities=entities,
                    )
                    self._last_sent_text = text
                except pyrogram.errors.exceptions.bad_request_400.MessageNotModified:
                    pass
                except Exception as e:
                    logger.error(f"Error editing final message: {e}")
            elif not self.reply_message:
                await self._send_new_message(text)
        if self.reply_message and self.is_group_chat and self.user and self.user.id:
            bot_reply = datatype.BotLastReply(
                message_id=self.reply_message.id,
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
