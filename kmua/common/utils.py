import random

import pyrogram


def get_msg_link(message: pyrogram.types.Message) -> str:
    try:
        chat = message.chat
        if chat is None:
            raise ValueError("Chat is None")
        link = f"https://t.me/c/{str(chat.id).removeprefix('-100')}/{message.id}"
        return link
    except Exception as e:
        return ""


def parse_msg_link(link: str) -> tuple[int, int] | None:
    split_link = link.split("/")
    try:
        chat_id = int("-100" + split_link[-2])
        message_id = int(split_link[-1])
    except ValueError:
        return None
    return chat_id, message_id


def random_chance(probability: float) -> bool:
    """Returns True with a given probability."""
    # probability should be between 0 and 1
    if probability < 0:
        return False
    if probability > 1:
        return True
    return random.uniform(0, 1) < probability
