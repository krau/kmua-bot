# https://github.com/kozalosev/DickGrowerBot/blob/main/src/handlers/utils/tghack.rs
import base64
import struct
from dataclasses import dataclass


class InvalidIDFormat(Exception):
    pass


@dataclass
class InlineMessageIdInfo:
    dc_id: int
    chat_id: int
    message_id: int
    access_hash: int


def _fix_chat_id(number: int) -> int:
    if number < 0:
        digits = len(str(abs(number)))
        return -100 * (10**digits) + number
    return number


def resolve_inline_message_id(inline_message_id: str) -> InlineMessageIdInfo:
    padded = inline_message_id + "=" * ((4 - len(inline_message_id) % 4) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded)
    except base64.binascii.Error as e:
        raise InvalidIDFormat(f"IDDecodeError: {e}")

    length = len(inline_message_id)
    if length == 27:
        fmt = "<iiiq"
        order = ("dc_id", "message_id", "chat_id", "access_hash")
    elif length == 32:
        fmt = "<iqiq"
        order = ("dc_id", "chat_id", "message_id", "access_hash")
    else:
        raise InvalidIDFormat(
            f"InvalidIDLength({length}): expected 27 or 32 characters"
        )

    try:
        parts = struct.unpack(fmt, raw)
    except struct.error as e:
        raise InvalidIDFormat(f"IdIoError: {e}")

    data = dict(zip(order, parts))
    data["chat_id"] = _fix_chat_id(data["chat_id"])
    return InlineMessageIdInfo(**data)
