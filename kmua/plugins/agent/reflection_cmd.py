from pyrogram import filters
from pyrogram.client import Client
from pyrogram.types import Message

from kmua.config import app_config
from kmua.plugins.agent.reflection import (
    generate_reflection_post,
    get_perception_summary,
    publish_reflection_post,
)


@Client.on_message(filters.command("reflect") & filters.user(app_config.owners))
async def cmd_reflect(client: Client, message: Message):
    """
    手动触发反思贴文发布

    仅限 owner 使用
    """
    if not app_config.agent:
        await message.reply_text("❌ Agent 功能未启用")
        return

    if not app_config.fans_channel:
        await message.reply_text("❌ 未配置 fans_channel")
        return

    status_msg = await message.reply_text("🤔 正在生成反思贴文...")

    try:
        success = await publish_reflection_post(client)

        if success:
            await status_msg.edit_text(
                f"✅ 反思贴文已发布到频道\n频道: {app_config.fans_channel}"
            )
        else:
            await status_msg.edit_text("❌ 发布失败，请查看日志")
    except Exception as e:
        await status_msg.edit_text(f"❌ 发生错误: {e}")


@Client.on_message(filters.command("perception") & filters.user(app_config.owners))
async def cmd_perception(client: Client, message: Message):
    """
    查看当前感知状态

    仅限 owner 使用
    """
    try:
        summary = await get_perception_summary()

        text = f"""📊 **当前感知状态**

⚡ **活跃度**: {summary["activity"]["message_volume"]:.2f}
❓ **问题压力**: {summary["activity"]["question_pressure"]:.2f}
🎯 **指向性**: {summary["activity"]["directedness"]:.2f}

😊 **情绪强度**: {summary["emotion"]["intensity"]:.2f}
💭 **情绪倾向**: {summary["emotion"]["valence"]:.2f}

🧠 **话题复杂度**: {summary["cognitive"]["complexity"]:.2f}
😴 **疲劳度**: {summary["cognitive"]["fatigue"]:.2f}
✨ **新鲜感**: {summary["cognitive"]["novelty"]:.2f}

🔥 **热门主题**:
"""

        if summary["topics"]:
            for topic, score in summary["topics"].items():
                text += f"  • {topic}: {score:.2f}\n"
        else:
            text += "  暂无主题数据\n"

        await message.reply_text(text)
    except Exception as e:
        await message.reply_text(f"❌ 获取状态失败: {e}")


@Client.on_message(filters.command("testpost") & filters.user(app_config.owners[0]))
async def cmd_testpost(client: Client, message: Message):
    """
    仅生成贴文预览，不发布

    仅限 owner 使用
    """
    if not app_config.agent:
        await message.reply_text("❌ Agent 功能未启用")
        return

    status_msg = await message.reply_text("🤔 正在生成贴文...")

    try:
        post_text = await generate_reflection_post()

        if post_text:
            await status_msg.edit_text(
                f"📝 **贴文预览**\n\n{post_text}\n\n（这只是预览，未实际发布）"
            )
        else:
            await status_msg.edit_text("❌ 生成失败")
    except Exception as e:
        await status_msg.edit_text(f"❌ 发生错误: {e}")
