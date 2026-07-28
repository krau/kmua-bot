from pyrogram import filters, types
from pyrogram.client import Client

from kmua import database, gift
from kmua.gift.service import send_gift_to_bot


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
    try:
        result = await send_gift_to_bot(user_id, gift_db_id)
    except ValueError as e:
        messages = {
            "Gift not found": "礼物未找到",
            "This is not your gift": "这不是你的礼物哦",
            "Gift was already sent": "这件礼物已经送过了哦",
            "Unknown gift": "收到了一件奇怪的礼物呢",
        }
        await callback_query.answer(messages.get(str(e), "送礼失败"), show_alert=True)
        return
    if result.detail and callback_query.message:
        await callback_query.message.reply_text(result.detail)
    await callback_query.answer(
        f"成功送出 {result.rarity_name}的{result.display_name} *1",
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
