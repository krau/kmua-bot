from pydantic_ai import ModelRetry, RunContext

from kmua.logger import logger
from kmua.plugins.agent import datatype, powermem_usage, quota


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
    with powermem_usage.collect() as memory_calls:
        results = await ctx.deps.powermemory.search(
            query, user_id=f"group_{ctx.deps.chat_id}", limit=10
        )
    # powermem 自己调模型, 用量只有它的回调看得到; 记到这次运行的人头上, 和这次运行的
    # 其它开销一样。
    await _settle_powermem(ctx, memory_calls)

    # powermem search response: entries under "results", each carrying "memory"
    # (plus metadata/score/id fields this tool ignores).
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
        with powermem_usage.collect() as memory_calls:
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
    except Exception as e:
        logger.error(
            f"update_group_memory: failed for group {ctx.deps.chat_id}: "
            f"{e.__class__.__name__}: {e}"
        )
        raise ModelRetry(f"Failed to store memory: {e.__class__.__name__}: {e}")
    # 计费发生在存储成功之后, 也不放在上面的 try 里: 结算失败不该被当成"没存进去"
    # 而让模型重试。
    await _settle_powermem(ctx, memory_calls)
    return f"Memory stored: {content!r}"


async def _settle_powermem(
    ctx: RunContext[datatype.ContextDeps], calls: list[tuple[int, int]]
) -> None:
    """Charge the tokens powermem spent on this tool call to the same account."""
    usage = powermem_usage.usage_of(calls)
    if usage is None:
        return
    await quota.settle(quota.subject_of(ctx.deps.message), usage)
