from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

BACKHOME_MARKUP = InlineKeyboardMarkup(
    [
        [
            InlineKeyboardButton("Back", callback_data="back_home"),
        ]
    ]
)

FAKE_USERS_ID = [136817688, 1087968824, 777000]


qer_quote_manage_button = [
    InlineKeyboardButton(
        "看看别人的",
        callback_data="qer_quote_manage",
    )
]

user_quote_manage_button = [
    InlineKeyboardButton(
        "看看我的",
        callback_data="user_quote_manage",
    )
]


no_quote_markup = InlineKeyboardMarkup(
    [
        qer_quote_manage_button,
        [
            InlineKeyboardButton(
                "返回",
                callback_data="back_home",
            )
        ],
    ],
)


LOADING_WORDS = [
    "少女祈祷中",
    "少女折寿中",
    "喵喵喵喵中",
    "色图绘制中",
    "请坐和放宽",
    "海内存知己, 天涯若比邻",
    "这可能需要1点时间",
    "这可能需要2点时间",
    "这可能需要3点时间",
    "这可能需要几个世纪",
    "请勿关闭电脑",
    "请勿关闭手机",
    "快到我床上中",
    "床上贴贴中",
    "床上睡觉中",
    "色图发送中",
    "少女摇补子中",
    "少女玩郊狼中",
    "少女伪街中",
    "少女炼铜中",
    "少女抽卡中",
    "少女更新蒸汽平台中",
    "少女写bug中",
    "少女改bug中",
    "少女吃麦当劳中",
    "少女面姬中",
    "少女抱抱中",
    "少女贴贴中",
    "少女摸摸中",
    "少女0721中",
    "少女喵喵中",
    "少女看番中",
    "Loading...",
    "少女离家出走中",
    "少女睡觉中",
    "少女熬夜中",
    "少女 ALL PERFECT 中",
    "少女粉绝赞中",
    "少女 FULL COMBO 中",
    "少女吹风扇中",
    "少女比心心中",
    "正在 cos 猫娘",
    "少女原神中",
    "玩命加载中",
    "QAQ中",
    "qwq中",
    "ovo中",
    "少女吃糖中",
    "少女报菜名中",
    "少女呜呜中",
    "少女😣中",
    "少女爱发电中",
    "少女围着你转中",
    "少女艾草中",
    "少女打📐中",
]
