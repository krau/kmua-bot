import random

from pyrogram import enums, filters, types
from pyrogram.client import Client

from kmua import database, gift


@Client.on_message(filters.command("buygift") & filters.private, group=1)
async def buy_gift(client: Client, message: types.Message):
    user = message.from_user
    if user is None:
        return
    user_data = await database.get_user_by_id(user.id)
    if not user_data:
        return
    user_coin = user_data.user_config.coins
    affordable_gifts = gift.list_affordable_gifts(user_coin)
    if not affordable_gifts:
        await message.reply_text("你现在似乎不能买任何礼物呢")
        return
    gift_list_text = "要买点什么呢?"
    await message.reply_text(
        gift_list_text,
        reply_markup=types.InlineKeyboardMarkup(
            [
                [
                    types.InlineKeyboardButton(
                        gift.get_display_name(g.id),
                        callback_data=f"buygift:{user.id}:{g.id}:req",
                    )
                    for g in affordable_gifts  # [TODO] 分个页, 等以后礼物类型多了的时候
                ],
                [
                    types.InlineKeyboardButton(
                        "离开",
                        callback_data="delete_callback_query_message",
                    )
                ],
            ]
        ),
    )


@Client.on_callback_query(filters.regex(r"^buygift:(\d+):(.+):(.+)$"), group=1)
async def handle_buy_gift_callback(client: Client, callback_query: types.CallbackQuery):
    data = callback_query.data
    if data is None:
        return
    data = str(data)
    parts = data.split(":")
    if len(parts) != 4:
        return
    user_id_str, gift_id_str, status = parts[1], parts[2], parts[3]
    try:
        user_id = int(user_id_str)
    except ValueError:
        return
    if callback_query.from_user.id != user_id:
        await callback_query.answer("这不是你的购买请求哦", show_alert=True)
        return
    gift_id = gift.GiftID(gift_id_str)
    gift_item = gift.get_gift_by_id(gift_id)
    user_data = await database.get_user_by_id(user_id)
    if not user_data:
        await callback_query.answer("用户数据未找到", show_alert=True)
        return
    user_coins = user_data.user_config.coins
    match status:
        case "yes":
            if user_data.user_config.coins < gift_item.price:
                await callback_query.answer(
                    "你的余额似乎不足以购买此礼物呢", show_alert=True
                )
                return
            rarity = random.randint(1, 5)
            await database.buy_gift_for_user(user_id, gift_id, rarity=rarity)
            await callback_query.answer(
                f"成功购买了 {gift.get_rarity_display_name(rarity)}的{gift.get_display_name(gift_item.id)} *1",
                show_alert=True,
            )
            user_coins_after = (await database.get_user_config(user_id)).coins
            percent_now = gift_item.price * 100 // user_coins_after
            if percent_now > 100 or user_coins <= 0:
                percent_now = 100
            await callback_query.edit_message_text(
                f"要再次购买 {gift.get_display_name(gift_item.id)} 吗?\n这将花费你 {percent_now}% 的余额哦",
                reply_markup=types.InlineKeyboardMarkup(
                    [
                        [
                            types.InlineKeyboardButton(
                                "再买一个",
                                callback_data=f"buygift:{user_id}:{gift_id_str}:yes",
                            ),
                            types.InlineKeyboardButton(
                                "离开",
                                callback_data="delete_callback_query_message",
                            ),
                        ]
                    ]
                ),
            )
        case "no":
            affordable_gifts = gift.list_affordable_gifts(user_coins)
            if not affordable_gifts:
                await callback_query.edit_message_text(
                    "已取消购买\n你现在似乎不能买任何礼物呢",
                    reply_markup=None,  # type: ignore
                )
                return
            gift_list_text = "已取消购买, 要买点其他的什么呢?"
            await callback_query.edit_message_text(
                gift_list_text,
                reply_markup=types.InlineKeyboardMarkup(
                    [
                        [
                            types.InlineKeyboardButton(
                                gift.get_display_name(g.id),
                                callback_data=f"buygift:{user_data.id}:{g.id}:req",
                            )
                            for g in affordable_gifts
                        ],
                        [
                            types.InlineKeyboardButton(
                                "离开",
                                callback_data="delete_callback_query_message",
                            )
                        ],
                    ]
                ),
            )
        case "req":
            price_percent = (
                int((gift_item.price / user_coins) * 100) if user_coins > 0 else 0
            )
            if price_percent > 100:
                price_percent = 100
            display_name = gift.get_display_name(gift_item.id)
            text = f"<b>{display_name}</b>\n<i>{gift_item.description}</i>\n\n效果注释: {gift_item.comment}\n\n你确定要购买 {display_name}*1 吗? 这将花费你 {price_percent}% 的余额哦"
            await callback_query.message.edit_text(
                text=text,
                parse_mode=enums.ParseMode.HTML,
                reply_markup=types.InlineKeyboardMarkup(
                    [
                        [
                            types.InlineKeyboardButton(
                                "确认",
                                callback_data=f"buygift:{user_id}:{gift_id_str}:yes",
                            ),
                            types.InlineKeyboardButton(
                                "算了",
                                callback_data=f"buygift:{user_id}:{gift_id_str}:no",
                            ),
                        ]
                    ]
                ),
            )
        case _:
            await callback_query.answer("未知操作", show_alert=True)
            return


@Client.on_message(filters.command("gift") & filters.private, group=1)
async def send_gift(client: Client, message: types.Message):
    user = message.from_user
    if user is None:
        return
    user_data = await database.get_user_by_id(user.id)
    if not user_data:
        return
    user_gifts = await database.get_user_gifts(user.id, False, 0, 5)
    if not user_gifts:
        await message.reply_text("你还没有买下任何礼物哦")
        return
    user_gifts_total = await database.count_user_gifts(user.id, False)
    text = "要送什么给咱呢? 点击序号按钮即可赠送"
    for i, g in enumerate(user_gifts, start=1):
        text += f"\n{i}. {gift.get_rarity_display_name(g.rarity)}的{gift.get_display_name(gift.GiftID(g.gift_id))}"
    # 每行5个按钮, 第2行分页
    buttons = [
        [
            types.InlineKeyboardButton(
                str(i + 1),
                callback_data=f"gift:{g.id}:0",  # sendgift:DB_GIFT_ID:OFFSET
            )
            for i, g in enumerate(user_gifts)
        ]
    ]
    if user_gifts_total >= 5:
        buttons.append(
            [
                types.InlineKeyboardButton(
                    "上一页",
                    callback_data="sendgift_page:-5",  # sendgift_page:OFFSET
                ),
                types.InlineKeyboardButton(
                    "下一页",
                    callback_data="sendgift_page:5",  # sendgift_page:OFFSET
                ),
            ]
        )
    await message.reply_text(
        text,
        reply_markup=types.InlineKeyboardMarkup(buttons),
    )


@Client.on_callback_query(filters.regex(r"^sendgift_page:.+$"), group=1)
async def handle_send_gift_page_callback(
    client: Client, callback_query: types.CallbackQuery
):
    data = callback_query.data
    if data is None:
        return
    data = str(data)
    parts = data.split(":")
    if len(parts) != 2:
        return
    offset_str = parts[1]
    try:
        offset = int(offset_str)
    except ValueError:
        return
    if offset < 0:
        await callback_query.answer("没有更多了哦", show_alert=True)
    user_id = callback_query.from_user.id
    user_data = await database.get_user_by_id(user_id)
    if not user_data:
        await callback_query.answer("用户数据未找到", show_alert=True)
        return
    user_gifts = await database.get_user_gifts(user_id, False, offset, 5)
    if not user_gifts:
        await callback_query.answer("没有更多礼物了哦", show_alert=True)
        return
    user_gifts_total = await database.count_user_gifts(user_id, False)
    text = "要送什么给咱呢? 点击序号按钮即可赠送"
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
