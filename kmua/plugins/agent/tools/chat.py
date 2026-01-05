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


async def search_group_memory(
    ctx: RunContext[datatype.ContextDeps], query: str
) -> list[str]:
    """Search the group chat memory.

    Arguments:
        query -- The search query, should be short and descriptive.

    Returns:
        A list of strings representing the chat memory entries. If no entries found, returns an empty list.
    """
    if not ctx.deps.powermemory:
        return []
    results = await ctx.deps.powermemory.search(
        query, user_id=f"group_{ctx.deps.chat_id}", limit=10
    )

    # - "results" (List[Dict]): List of memory search results, where each result contains:
    #     - "memory" (str): The memory content
    #     - "metadata" (Dict): Metadata associated with the memory
    #     - "score" (float): Similarity score for the result
    #     - "id" (int, optional): Memory ID
    #     - "created_at" (datetime, optional): Creation timestamp
    #     - "updated_at" (datetime, optional): Update timestamp
    #     - "user_id" (str, optional): User ID
    #     - "agent_id" (str, optional): Agent ID
    #     - "run_id" (str, optional): Run ID
    # - "relations" (List, optional): Graph relations if graph store is enabled
    return [res.get("memory", "") for res in results.get("results", [])]
