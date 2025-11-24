import uuid

from pyrogram import types
from pyrogram.client import Client

from kmua.common.memory_store import memttlcache

from . import drawer as manodrawer
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
            if len(text) > 233:
                text = text[:233]
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
                        title=f"安安说 [{face}]",
                        description="将在发送后生成",
                        id=f"ms_{dataid}",
                        input_message_content=types.InputTextMessageContent(
                            message_text="安安正在写字...",
                        ),
                        thumb_url="https://kmua.unv.app/assets/manosaba/anan_example.webp",
                        reply_markup=utils.markup_anan_tips,
                    )
                ]
            )
            return
        case "trial":
            # trial 角色 (statement text)...
            # 可以用中文或英文中括号
            if len(datas) < 2:
                await query.answer(
                    results=[
                        utils.result_trial_ema_tips,
                        utils.result_trial_hiro_tips,
                    ],
                )
                return
            character = manodrawer.get_character(datas[1])
            if len(datas) < 4:
                await query.answer(
                    results=[
                        utils.result_trial_ema_tips
                        if character == manodrawer.Character.EMA
                        else utils.result_trial_hiro_tips,
                    ],
                )
                return
            options = utils.parse_options(" ".join(datas[2:]))
            if not options:
                await query.answer(
                    results=[
                        utils.result_trial_ema_tips,
                        utils.result_trial_hiro_tips,
                    ],
                )
                return
            if len(options) > 4:
                options = options[:4]
            for opt in options:
                if len(opt.text) > 100:
                    opt.text = opt.text[:100]
            data = {
                "type": "trial",
                "character": character,
                "options": options,
            }
            dataid = uuid.uuid4().hex
            await memttlcache.set(f"manomeme_inline:{dataid}", data, 300)
            is_hiro = character == manodrawer.Character.HIRO
            title_char = "艾玛" if not is_hiro else "希罗"
            await query.answer(
                results=[
                    types.InlineQueryResultArticle(
                        title=f"{title_char} [{'|'.join([opt.statement.display for opt in options])}]",
                        description="将在发送后生成",
                        id=f"ms_{dataid}",
                        input_message_content=types.InputTextMessageContent(
                            message_text=f"{title_char} 正在穷举..."
                            if not is_hiro
                            else f"{title_char} 正在思考...",
                        ),
                        reply_markup=(
                            utils.markup_trial_ema_tips
                            if not is_hiro
                            else utils.markup_trial_hiro_tips
                        ),
                        thumb_url=f"https://kmua.unv.app/assets/manosaba/{'emadog' if not is_hiro else 'hirocat'}.webp",
                    )
                ]
            )
            return
