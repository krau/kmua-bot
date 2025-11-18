import asyncio
import uuid

from pyrogram import types
from pyrogram.client import Client

from kmua.common.memory_store import memttlcache
from kmua.plugins.inlinequery import manodrawer

from . import utils


async def handle_manomeme(
    client: Client,
    query: types.InlineQuery,
    datas: list[str],
):
    if not datas:
        await query.answer(
            results=[
                utils.result_anan_tips,
                utils.result_trial_ema_tips,
                utils.result_trial_hiro_tips,
            ],
        )
        return
    meme_type = datas[0]
    match meme_type:
        case "anan":
            # anan 表情 文本
            if len(datas) < 3:
                await query.answer(
                    results=[utils.result_anan_tips],
                )
                return
            face = datas[1]
            if face not in utils.anan_faces:
                await query.answer(
                    results=[utils.result_anan_tips],
                )
                return
            text = " ".join(datas[2:])
            data = {
                "type": "anan",
                "face": face,
                "text": text,
            }
            dataid = uuid.uuid4().hex
            await memttlcache.set(f"manomeme_inline:{dataid}", data, 300)
            await query.answer(
                results=[
                    types.InlineQueryResultArticle(
                        title=f"[{face}] 安安说",
                        description="将在发送后生成",
                        id=f"ms_{dataid}",
                        input_message_content=types.InputTextMessageContent(
                            message_text="安安正在写字...",
                        ),
                        reply_markup=utils.markup_anan_tips,
                    )
                ]
            )
            return
        case "trial":
            pass
