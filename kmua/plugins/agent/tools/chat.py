import pyrogram.types
from pydantic import BaseModel
from pydantic_ai import ModelRetry, RunContext

from kmua import database
from kmua.logger import logger
from kmua.plugins.agent import datatype


class ChatJoke(BaseModel):
    content: str
    sender_id: int
    sender_name: str
    created_at: str


async def send_chat_quote(ctx: RunContext[datatype.ContextDeps], query: str) -> str:
    """Search and send the chat in-jokes (or called "quote"/语录)

    Given a query, search the database for matching quotes and send the first match.
    The message will include a reply markup showing the source message and sender.

    Arguments:
        query -- The search query.

    Returns:
        A message indicating whether a quote was found and sent.
    """
    quotes = await database.get_chat_quotes(ctx.deps.chat_id, query, 1)
    if not quotes:
        raise ModelRetry("No matching quotes found. Try a different query.")

    quote = quotes[0]

    # Build sender button text (truncate if too long)
    user_button_text = (
        quote.user.full_name
        if len(quote.user.full_name) <= 16
        else quote.user.full_name[:16] + "..."
        if quote.user.full_name
        else str(quote.user_id)
    )

    # Send the quote message with reply markup showing sender and source
    await ctx.deps.client.copy_message(
        chat_id=ctx.deps.chat_id,
        from_chat_id=quote.chat_id,
        message_id=quote.message_id,
        reply_markup=pyrogram.types.InlineKeyboardMarkup(
            [[pyrogram.types.InlineKeyboardButton(user_button_text, url=quote.link)]]
        ),
    )

    return f"Sent quote: '{quote.text[:50] if quote.text else 'Non text content'}...' from {quote.user.full_name or quote.user_id}."


async def search_group_memory(
    ctx: RunContext[datatype.ContextDeps], query: str
) -> list[str]:
    """Search the group's long-term memory for information relevant to the query.

    Memory entries contain factual information about the group and its members,
    such as personal interests, relationships between members, past events, and
    other notable facts that have been observed over time.

    This tool uses semantic (vector) search — it finds entries that are
    conceptually related to the query, not just exact keyword matches. Use
    natural-language phrases or concepts rather than precise keywords for best
    results. For example, querying "outdoor activities" may surface memories
    about hiking, cycling, or camping even if those exact words differ.

    Args:
        query: A natural-language phrase describing what you want to find.

    Returns:
        A list of matching memory entries as strings. Returns an empty list if
        no relevant memories are found.
    """
    logger.debug(
        f"search_group_memory called with query='{query}' for chat_id={ctx.deps.chat_id}"
    )
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
