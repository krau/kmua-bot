from pydantic import BaseModel
from pydantic_ai import RunContext

from kmua import database
from kmua.plugins.agent import datatype


class ChatJoke(BaseModel):
    content: str
    sender_id: int
    sender_name: str
    created_at: str


async def search_chat_in_jokes(
    ctx: RunContext[datatype.ContextDeps], query: str
) -> list[ChatJoke]:
    """Search the chat in-jokes (or called "quote"/语录)

    Arguments:
        query -- The search query.

    Returns:
        A list of ChatJoke objects. If no jokes found, returns an empty list.
    """
    return [
        ChatJoke(
            content=quote.text or "",
            sender_id=quote.user.id,
            sender_name=quote.user.full_name,
            created_at=quote.created_at.isoformat(),
        )
        for quote in await database.get_chat_quotes(ctx.deps.chat_id, query, 10)
    ]
