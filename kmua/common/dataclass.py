from dataclasses import dataclass
from enum import Enum


class MessageType(Enum):
    TEXT = 1
    PHOTO = 2
    VIDEO = 3
    AUDIO = 4
    FILE = 5


@dataclass
class MessageInMeili:
    message_id: int
    text: str
    user_id: int
    type: MessageType

    def to_dict(self):
        return {
            "message_id": self.message_id,
            "text": self.text,
            "user_id": self.user_id,
            "type": self.type.value,
        }
