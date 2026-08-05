from pydantic_ai import ModelRetry, RunContext

from kmua.logger import logger
from kmua.plugins.agent import datatype


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


async def update_group_memory(
    ctx: RunContext[datatype.ContextDeps], content: str
) -> str:
    """Store a piece of information about this group into its long-term memory.

    Use this tool when you observe something worth remembering about the group
    or its members — for example, notable facts, recurring topics, preferences,
    relationships between members, or significant events. The memory system
    will infer structured facts from the text you provide.

    Only store genuinely useful, non-trivial information. Do not store
    conversational filler or information that is already in the current context.

    Args:
        content: A concise description of what should be remembered.
            Write it as a factual statement in natural language.

    Returns:
        A message confirming the memory was stored, or an error description.
    """
    if not ctx.deps.powermemory:
        return "Group memory system is not available."
    try:
        result = await ctx.deps.powermemory.add(
            content,
            infer=True,
            user_id=f"group_{ctx.deps.chat_id}",
            prompt="You are a helpful assistant that stores useful information about the group based on the following content. "
            "Extract any notable facts, relationships, preferences, or significant details that would be worth remembering about the group and its members.",
        )
        logger.debug(
            f"update_group_memory: stored memory for group {ctx.deps.chat_id}, "
            f"powermem result: {result}"
        )
        return f"Memory stored: {content!r}"
    except Exception as e:
        logger.error(
            f"update_group_memory: failed for group {ctx.deps.chat_id}: "
            f"{e.__class__.__name__}: {e}"
        )
        raise ModelRetry(f"Failed to store memory: {e.__class__.__name__}: {e}")
