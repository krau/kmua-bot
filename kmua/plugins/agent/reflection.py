"""
reflection - agent 的自我反思和贴文发布系统

定期根据全局感知状态生成并发布贴文到粉丝频道
"""

from pydantic_ai import Agent, ModelMessage, ModelMessagesTypeAdapter
from pyrogram.client import Client

from kmua.common.memory_store import memttlcache
from kmua.config import app_config
from kmua.logger import logger
from kmua.plugins.agent import state
from kmua.plugins.agent.consciousness import (
    create_snapshot,
    generate_post_prompt,
    get_global_state,
)

from .agent import model


def history_processor(messages: list[ModelMessage]) -> list[ModelMessage]:
    # 保留最后10条消息作为上下文
    return messages[-10:]


# 创建用于生成贴文的 agent
reflection_agent = Agent(
    model=model,
    system_prompt=f"""{app_config.agent_prompt}
{app_config.agent_reflection_prompt}
""",
    history_processors=[history_processor],
)


async def generate_reflection_post() -> str | None:
    """
    生成反思贴文

    Returns:
        str | None: 生成的贴文内容，失败返回 None
    """
    try:
        prompt = generate_post_prompt()
        logger.debug(f"Generating reflection post with prompt: {prompt[:100]}...")
        history_data: bytes = await memttlcache.get(state.agent_reflection_post_history)
        history = None
        if history_data:
            history = ModelMessagesTypeAdapter.validate_json(history_data)
        result = await reflection_agent.run(prompt, message_history=history)
        await memttlcache.set(
            state.agent_reflection_post_history,
            result.all_messages_json(),
            ttl=86400 * 7,
        )
        post_text = result.output.strip()

        logger.info(f"Generated reflection post: {post_text[:50]}...")
        return post_text
    except Exception as e:
        logger.error(f"Failed to generate reflection post: {e}")
        return None


async def publish_reflection_post(client: Client) -> bool:
    """
    发布反思贴文到粉丝频道
    """
    if not app_config.fans_channel:
        logger.warning("fans_channel not configured, skipping reflection post")
        return False

    # 检查是否启用了 agent
    if not app_config.agent:
        return False

    # 生成贴文
    post_text = await generate_reflection_post()
    if not post_text:
        return False

    try:
        full_text = post_text

        # 发送到频道
        await client.send_message(
            chat_id=app_config.fans_channel,
            text=full_text,
        )

        logger.success(
            f"Published reflection post to fans_channel: {app_config.fans_channel}"
        )

        # 创建当前状态的快照，用于下次对比
        create_snapshot()
        logger.debug("Created state snapshot after publishing post")

        return True
    except Exception as e:
        logger.error(f"Failed to publish reflection post: {e}")
        return False


async def get_perception_summary() -> dict:
    """
    获取当前感知状态的摘要（用于调试或展示）

    Returns:
        dict: 状态摘要
    """
    state = get_global_state()

    return {
        "activity": {
            "message_volume": state.message_volume,
            "question_pressure": state.question_pressure,
            "directedness": state.directedness,
        },
        "emotion": {
            "intensity": state.emotional_intensity,
            "valence": state.emotional_valence,
        },
        "cognitive": {
            "complexity": state.complexity,
            "novelty": state.novelty_decay,
        },
        "topics": dict(
            list(
                sorted(state.dominant_topics.items(), key=lambda x: x[1], reverse=True)[
                    :10
                ]
            )
        ),
    }
