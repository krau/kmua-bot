import re

from pyrogram import types
from pyrogram.client import Client

from kmua.plugins.inlinequery import manodrawer

anan_faces = [
    "病娇",
    "生气",
    "害羞",
    "无语",
    "开心",
]

# tips means that user didn't provide enough arguments
markup_anan_tips = types.InlineKeyboardMarkup(
    [
        [
            types.InlineKeyboardButton(
                text="病娇",
                switch_inline_query_current_chat="ms anan 病娇 ",
            ),
            types.InlineKeyboardButton(
                text="生气",
                switch_inline_query_current_chat="ms anan 生气 ",
            ),
        ],
        [
            types.InlineKeyboardButton(
                text="害羞",
                switch_inline_query_current_chat="ms anan 害羞 ",
            ),
            types.InlineKeyboardButton(
                text="无语",
                switch_inline_query_current_chat="ms anan 无语 ",
            ),
            types.InlineKeyboardButton(
                text="开心",
                switch_inline_query_current_chat="ms anan 开心 ",
            ),
        ],
    ]
)

markup_trial_ema_tips = types.InlineKeyboardMarkup(
    [
        [
            types.InlineKeyboardButton(
                text="赞同",
                switch_inline_query_current_chat="ms trial 艾玛 [赞同]",
            ),
            types.InlineKeyboardButton(
                text="疑问",
                switch_inline_query_current_chat="ms trial 艾玛 [疑问]",
            ),
        ],
        [
            types.InlineKeyboardButton(
                text="反驳",
                switch_inline_query_current_chat="ms trial 艾玛 [反驳]",
            ),
            types.InlineKeyboardButton(
                text="伪证",
                switch_inline_query_current_chat="ms trial 艾玛 [伪证]",
            ),
        ],
    ]
)

markup_trial_hiro_tips = types.InlineKeyboardMarkup(
    [
        [
            types.InlineKeyboardButton(
                text="伪证",
                switch_inline_query_current_chat="ms trial 希罗 [伪证] ",
            ),
            types.InlineKeyboardButton(
                text="反驳",
                switch_inline_query_current_chat="ms trial 希罗 [反驳]",
            ),
        ],
        [
            types.InlineKeyboardButton(
                text="赞同",
                switch_inline_query_current_chat="ms trial 希罗 [赞同]",
            ),
            types.InlineKeyboardButton(
                text="疑问",
                switch_inline_query_current_chat="ms trial 希罗 [疑问]",
            ),
        ],
    ]
)

result_anan_tips: types.InlineQueryResultArticle = types.InlineQueryResultArticle(
    title="安安说",
    input_message_content=types.InputTextMessageContent(message_text="让吾辈「说话」"),
    description="用法: ms anan [表情] [文本]",
    thumb_url="https://kmua.unv.app/assets/manosaba/anan_example.webp",
    reply_markup=markup_anan_tips,
)

result_trial_ema_tips: types.InlineQueryResultAnimation = (
    types.InlineQueryResultAnimation(
        title="辩论-艾玛",
        description="开始穷举",
        animation_url="https://kmua.unv.app/assets/manosaba/trial_ema.mp4",
        caption="选择「在意的地方」",
        reply_markup=markup_trial_ema_tips,
    )
)

result_trial_hiro_tips: types.InlineQueryResultAnimation = (
    types.InlineQueryResultAnimation(
        title="辩论-希罗",
        description="神秘伪证女",
        animation_url="https://kmua.unv.app/assets/manosaba/trial_hiro.mp4",
        caption="开始你的伪证",
        reply_markup=markup_trial_hiro_tips,
    )
)


def parse_options(text: str) -> list[manodrawer.Option]:
    """
    Parse statement-text pairs from the format:
    statement text statement text ...
    Where:
      - statement may be plain:   赞同
      - or bracketed:             [赞同], 【疑问】, etc.
      - text may be plain or in double quotes; quoted text is treated as a single unit
    """
    # 1. 全部合法的 statement 文本
    stmt_words = ["赞同", "疑问", "反驳", "伪证"]

    # 2. 构造匹配 statement 的正则：支持三种格式
    #    - 赞同
    #    - [赞同]
    #    - 【赞同】
    stmt_pattern = (
        r"(?:"
        r"[\\[【](" + "|".join(stmt_words) + r")[\\]】]"  # 带括号
        r"|(" + "|".join(stmt_words) + r")"  # 不带括号
        r")"
    )

    # 3. text 的匹配（双引号整体 or 普通非空白字段）
    #    - "quoted text"
    #    - plain text until next statement
    token_pattern = re.compile(
        rf"""
        \s*(
            "{1}[^"]*"{1}
            |
            [^\s]+
        )""",
        re.VERBOSE,
    )

    # 4. 首先找到所有 statement 的位置
    stmt_regex = re.compile(stmt_pattern)
    stmts = list(stmt_regex.finditer(text))

    if not stmts:
        return []

    options: list[manodrawer.Option] = []

    for i, stmt_match in enumerate(stmts):
        # 得到 statement 文本（可能来自 group1 或 group2）
        stmt_str = stmt_match.group(1) or stmt_match.group(2)
        stmt_enum = manodrawer.get_statement(stmt_str)

        start = stmt_match.end()
        end = stmts[i + 1].start() if i + 1 < len(stmts) else len(text)

        segment = text[start:end].strip()

        if not segment:
            continue

        # 解析 text，若有引号则保持整体
        tokens = [t.strip() for t in token_pattern.findall(segment)]

        # 若第一个 token 是引号包住的，去掉引号内容即可
        first = tokens[0]
        if first.startswith('"') and first.endswith('"'):
            content = first[1:-1]  # remove quotes
        else:
            # 没有引号时，整个 segment 是内容
            content = segment

        options.append(manodrawer.Option(stmt_enum, content))

    return options
