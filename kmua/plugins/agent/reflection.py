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
from kmua.plugins.agent.consciousness import generate_post_prompt, get_global_state

from .agent import model


def history_processor(messages: list[ModelMessage]) -> list[ModelMessage]:
    # 保留最后10条消息作为上下文
    return messages[-10:]


# 创建用于生成贴文的 agent
reflection_agent = Agent(
    model=model,
    system_prompt=f"""{app_config.agent_prompt}
---
**特殊任务说明 - 撰写反思贴文**:
你需要定期根据自己对近期对话的观察和体验，撰写一条简短的个人感想贴文发布到粉丝频道。

贴文要求：
1. 以第一人称视角，分享你对近期对话的真实感受和观察
2. 可以提及印象深刻的话题、有趣的互动、或当前的状态（如活跃、疲惫、开心等）
3. 表达要自然、有个性，符合你的角色设定，不要太官方或机械
4. 字数要简短, 最多不超过 100 字
5. 不要使用 markdown 格式，纯文本即可
6. 语气要真诚、轻松，就像和朋友分享日常一样
7. 可以适当表达情绪，但不要过度煽情

记住，你是在和关注你的人分享近期的体验和感受，要让他们感受到你的"存在感"和个性。
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
            "fatigue": state.fatigue,
            "novelty": state.novelty_decay,
        },
        "topics": dict(
            list(
                sorted(state.dominant_topics.items(), key=lambda x: x[1], reverse=True)[
                    :5
                ]
            )
        ),
    }
