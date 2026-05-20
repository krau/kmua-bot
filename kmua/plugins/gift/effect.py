from pyrogram import filters, types
from pyrogram.client import Client

from kmua import affection, common, database, gift
from kmua.plugins.agent import state


@Client.on_callback_query(filters.regex(r"^gift:.+:.+$"), group=1)
async def handle_send_gift_callback(
    client: Client, callback_query: types.CallbackQuery
):
    data = callback_query.data
    if data is None:
        return
    data = str(data)
    parts = data.split(":")
    if len(parts) != 3:
        return
    user_id = callback_query.from_user.id
    gift_db_id_str = parts[1]
    try:
        gift_db_id = int(gift_db_id_str)
    except ValueError:
        return
    offset_str = parts[2]
    try:
        offset = int(offset_str)
    except ValueError:
        offset = 0
    user_data = await database.get_user_by_id(user_id)
    if not user_data:
        await callback_query.answer("用户数据未找到", show_alert=True)
        return
    gift_item = await database.get_gift_by_db_id(gift_db_id)
    if not gift_item:
        await callback_query.answer("礼物未找到", show_alert=True)
        return
    if gift_item.owner_id != user_data.id:
        # should not happen..
        await callback_query.answer("这不是你的礼物哦", show_alert=True)
        return
    if gift_item.sent_to_bot:
        await callback_query.answer("这件礼物已经送过了哦", show_alert=True)
        return
    gift_id = gift.GiftID(gift_item.gift_id)
    gift_def = gift.get_gift_by_id(gift_id)
    display_name = gift.get_display_name(gift_def.id)
    # maybe a verge ugly match case...
    match gift_def.id:
        case gift.GiftID.SEVERED_GRASS_SILENCE:
            # clear bot agent memory
            await common.memttlcache.delete(f"agent_user_memory:{user_id}")
        case gift.GiftID.VOW_LOTUS_SEAL:
            # prevent affection
            duration = gift_def.effects.get("duration", 0) * gift_item.rarity
            passivation = gift_def.effects.get("passivation", 0) * gift_item.rarity
            await common.memttlcache.set(
                f"affection_passivation:{user_id}", passivation, duration
            )
        case gift.GiftID.AMARANTH_HEART_LAMP:
            current = await affection.get_user_affection(user_id)
            add_affection = gift_def.effects.get("add_affection", 0) * gift_item.rarity
            duration = gift_def.effects.get("duration", 0) * gift_item.rarity
            await affection.set_user_temporary_affection(
                user_id=user_id,
                affection=current + add_affection,
                ttl=duration,
            )
        case gift.GiftID.FROST_FLOWER_WHISPER:
            # show memory and affection
            memory = await common.memttlcache.get(f"agent_user_memory:{user_id}", None)
            affection_rank = await affection.get_affection_rank(user_id)
            memory_text = memory if memory is not None else "无"
            await callback_query.message.reply_text(
                f"当前对你的记忆:\n{memory_text}\n\n好感度排名: {affection_rank:.2%}"
            )
        case gift.GiftID.DAWN_BELL_HERB:
            await common.memttlcache.delete(state.user_blocked_key(user_id))
            immune_duration = gift_def.effects.get("immune_duration", 0) * gift_item.rarity
            if immune_duration > 0:
                await common.memttlcache.set(
                    state.user_block_immune_key(user_id), True, ttl=immune_duration
                )
        case _:
            await callback_query.answer("收到了一件奇怪的礼物呢", show_alert=True)
            return
    # common effects
    affection_change = gift_def.effects.get("affection_change", 0)
    if affection_change != 0:
        await affection.update_user_affection(
            user_id=user_id,
            change=affection_change,
        )
    await database.mark_gift_as_sent(gift_db_id)
    await callback_query.answer(
        f"成功送出 {gift.get_rarity_display_name(gift_item.rarity)}的{display_name} *1",
        show_alert=True,
    )
    user_gifts = await database.get_user_gifts(user_id, False, offset, 5)
    user_gifts_total = await database.count_user_gifts(user_id, False)
    if not user_gifts:
        if user_gifts_total == 0:
            await callback_query.edit_message_text("礼物送完了哦")
            return
        else:
            offset = max(0, offset - 5)
            user_gifts = await database.get_user_gifts(user_id, False, offset, 5)
    text = "还要送些什么呢? 礼物效果不一定能叠加哦"
    for i, g in enumerate(user_gifts, start=1 + offset):
        text += f"\n{i}. {gift.get_rarity_display_name(g.rarity)}的{gift.get_display_name(gift.GiftID(g.gift_id))}"
    # 每行5个按钮, 第2行分页
    buttons = [
        [
            types.InlineKeyboardButton(
                str(i + 1 + offset),
                callback_data=f"gift:{g.id}:{offset}",  # sendgift:DB_GIFT_ID:OFFSET
            )
            for i, g in enumerate(user_gifts)
        ]
    ]
    if user_gifts_total >= 5:
        buttons.append(
            [
                types.InlineKeyboardButton(
                    "上一页",
                    callback_data=f"sendgift_page:{offset - 5}",  # sendgift_page:OFFSET
                ),
                types.InlineKeyboardButton(
                    "下一页",
                    callback_data=f"sendgift_page:{offset + 5}",  # sendgift_page:OFFSET
                ),
            ]
        )
    await callback_query.edit_message_text(
        text,
        reply_markup=types.InlineKeyboardMarkup(buttons),
    )
