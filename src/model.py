from datetime import datetime
from uuid import UUID


class ImgQuote:
    def __init__(self, id: UUID, content: str, text: str, created_at: datetime):
        self.id = id
        self.content = content
        self.text = text
        self.created_at = created_at

    def __repr__(self):
        return f"<ImgQuote id={self.id} created_at={self.created_at}>"

    def __str__(self):
        return self.__repr__()

    @classmethod
    def from_dict(cls, data: dict):
        return cls(
            id=data["id"], content=data["content"], created_at=data["created_at"]
        )

    def to_dict(self):
        return {"id": self.id, "content": self.content, "created_at": self.created_at}


class TextQuote:
    def __init__(self, id: UUID, content: str, created_at: datetime):
        self.id = id
        self.content = content
        self.created_at = created_at

    def __repr__(self):
        return f"<TextQuote id={self.id} created_at={self.created_at}>"

    def __str__(self):
        return self.__repr__()

    @classmethod
    def from_dict(cls, data: dict):
        return cls(
            id=data["id"], content=data["content"], created_at=data["created_at"]
        )

    def to_dict(self):
        return {"id": self.id, "content": self.content, "created_at": self.created_at}


class MemberData:
    def __init__(self, name: str, msg_num: int, id: int, quote_num: int) -> None:
        self.name = name
        self.msg_num = msg_num
        self.id = id
        self.quote_num = quote_num