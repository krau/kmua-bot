"""验证 challenge 的纯构建逻辑: 常量、题目生成、文案与键盘。"""

from __future__ import annotations

import random

from pyrogram.enums import ButtonStyle
from pyrogram.types import (
    CallbackQuery,
    ChatPermissions,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from kmua.database.models import ChatConfig, VerificationSession
from kmua.i18n import i18n

EMOJI_POOL = ["🍎", "🍌", "🍇", "🍓", "🍒", "🍑", "🥝", "🍍", "🥥", "🍉", "🍊", "🥭"]

# 内置默认题库; 格式同面板存储的 verify_questions。
DEFAULT_VERIFY_QUESTIONS: list[dict] = [
    {
        "question": "初音未来的头发是什么颜色?",
        "options": ["绿色", "蓝色", "粉色", "葱色"],
        "answers": ["绿色", "葱色"],
        "select": ["any"],
    },
    {
        "question": "《原神》中旅行者的旅伴是什么?",
        "options": ["派蒙", "嘟嘟可", "摩诃善法大吉祥智慧主", "若娜瓦"],
        "answers": ["派蒙"],
    },
]

# 解除限制必须全 True: 空 ChatPermissions() 会把用户完全静音。
UNRESTRICT_PERMISSIONS = ChatPermissions(
    can_send_messages=True,
    can_send_audios=True,
    can_send_documents=True,
    can_send_photos=True,
    can_send_videos=True,
    can_send_video_notes=True,
    can_send_voice_notes=True,
    can_send_polls=True,
    can_send_other_messages=True,
    can_add_web_page_previews=True,
    can_react_to_messages=True,
    can_edit_tag=True,
    can_change_info=True,
    can_invite_users=True,
    can_pin_messages=True,
    can_manage_topics=True,
)


# 贴纸验证不限制发言: 客户端把 send_messages 当总开关, 部分放行无效。
def restrict_permissions(method: str) -> ChatPermissions | None:
    """新成员入群施加的限制权限; 贴纸验证返回 None(不限制)。"""
    if method == "sticker":
        return None
    return ChatPermissions()


# --------------------------------------------------------------------------- 纯函数


def should_verify(strategy: str, is_bot: bool) -> bool:
    """按触发策略决定是否验证; 未知策略不验证, 防误伤。"""
    match strategy:
        case "all":
            return True
        case _:
            return False


def make_math_challenge() -> dict:
    """算术题: 两个 2..9 的加数, 4 个选项中含正确答案。"""
    a, b = random.randint(2, 9), random.randint(2, 9)
    answer = a + b
    pool = list(range(max(0, answer - 6), answer + 7))
    pool.remove(answer)
    distractors = random.sample(pool, 3)
    options = random.sample([answer] + distractors, 4)
    return {"a": a, "b": b, "answer": answer, "options": options}


def make_emoji_challenge() -> dict:
    """点选表情: 6 个选项中保证含目标表情。"""
    target = random.choice(EMOJI_POOL)
    rest = [e for e in EMOJI_POOL if e != target]
    options = [target] + random.sample(rest, 5)
    random.shuffle(options)
    return {"target": target, "options": options}


def make_sticker_challenge() -> dict:
    """贴纸验证: 任意贴纸即通过, 无需 payload。"""
    return {}


def make_qa_challenge(questions: list[dict]) -> dict:
    """随机取一条有效题目, 选项打乱, answers 为全部正确选项; 全无效时用默认题库。"""
    valid = [
        q
        for q in questions
        if isinstance(q, dict)
        and q.get("question")
        and isinstance(q.get("options"), list)
        and len(q["options"]) >= 2
        and isinstance(q.get("answers"), list)
        and len(q["answers"]) >= 1
        and all(answer in q["options"] for answer in q["answers"])
    ]
    if not valid:
        valid = DEFAULT_VERIFY_QUESTIONS
    question = random.choice(valid)
    options = list(question["options"])
    random.shuffle(options)
    return {
        "question": question["question"],
        "options": options,
        "answers": list(question["answers"]),
        "select": question.get("select", "all"),
    }


def _is_multi_answer(session_row: VerificationSession) -> bool:
    """custom_qa 全选模式: 多正确答案且必须全部选中(而非任选其一)。"""
    if session_row.method != "custom_qa":
        return False
    return _multi_payload(session_row.payload or {})


def _multi_payload(payload: dict) -> bool:
    """payload 是否全选模式: select=all 且正确答案多于一个。"""
    return (
        payload.get("select", "all") == "all" and len(payload.get("answers") or []) > 1
    )


def _callback_data(callback_query: CallbackQuery) -> list[str]:
    """回调数据按 ':' 拆分; 兼容 str/bytes/None(自定义按钮恒为 ASCII str)。"""
    data = callback_query.data or ""
    if isinstance(data, bytes):
        data = data.decode(errors="replace")
    return data.split(":")


def _is_correct_option(session_row: VerificationSession, index: int) -> bool:
    """点中的选项是否属于正确答案: emoji 按 target, math 按 answer,
    custom_qa 按 answers 集合(单选/多选通用)。"""
    payload = session_row.payload or {}
    options = payload.get("options") or []
    if index < 0 or index >= len(options):
        return False
    if session_row.method == "emoji":
        return options[index] == payload.get("target")
    answers = payload.get("answers")
    if isinstance(answers, list):
        return options[index] in answers
    return options[index] == payload.get("answer")


def build_challenge_text(
    config: ChatConfig,
    method: str,
    payload: dict,
    attempts_left: int,
    *,
    wrong_prefix: bool,
    lang: str,
    user_mention: str = "",
) -> str:
    """challenge 正文; user_mention 非空时作为首行。"""
    prefix = i18n.t("bot.msg.verify.wrong_prefix", locale=lang) if wrong_prefix else ""
    if method == "math":
        body = i18n.t("bot.msg.verify.challenge_math", locale=lang).format(
            a=payload["a"],
            b=payload["b"],
            attempts=attempts_left,
            max=config.verify_max_attempts,
        )
    elif method == "emoji":
        body = i18n.t("bot.msg.verify.challenge_emoji", locale=lang).format(
            emoji=payload["target"],
            attempts=attempts_left,
            max=config.verify_max_attempts,
        )
    elif method == "sticker":
        # 贴纸方法不存在答错, 仅超时
        body = i18n.t("bot.msg.verify.challenge_sticker", locale=lang)
    else:  # custom_qa
        key = (
            "bot.msg.verify.challenge_qa_multi"
            if _multi_payload(payload)
            else "bot.msg.verify.challenge_qa"
        )
        body = i18n.t(key, locale=lang).format(
            question=payload["question"],
            attempts=attempts_left,
            max=config.verify_max_attempts,
        )
    timeout_hint = i18n.t("bot.msg.verify.timeout_hint", locale=lang).format(
        timeout=config.verify_timeout_seconds
    )
    mention_line = f"{user_mention}\n" if user_mention else ""
    return mention_line + prefix + body + "\n" + timeout_hint


# --------------------------------------------------------------------------- 键盘


def _admin_row(session_id: int, lang: str) -> list[InlineKeyboardButton]:
    """放行/封禁两个管理员按钮, 所有验证方式一致。"""
    return [
        InlineKeyboardButton(
            i18n.t("bot.button.verify.approve", locale=lang),
            callback_data=f"verify_admin:{session_id}:approve",
            style=ButtonStyle.SUCCESS,
        ),
        InlineKeyboardButton(
            i18n.t("bot.button.verify.ban", locale=lang),
            callback_data=f"verify_admin:{session_id}:ban",
            style=ButtonStyle.DANGER,
        ),
    ]


def _challenge_markup(
    session_row: VerificationSession, lang: str
) -> InlineKeyboardMarkup:
    """作答行(math 2x2 / emoji 2x3 / custom_qa 2xN, 多选带确认行) + 管理员行。"""
    rows: list[list[InlineKeyboardButton]] = []
    payload = session_row.payload or {}
    options = payload.get("options") or []
    if session_row.method in ("math", "custom_qa"):
        selected = set(payload.get("selected") or [])
        buttons = [
            InlineKeyboardButton(
                (
                    f"{option} {i18n.t('bot.button.verify.selected', locale=lang)}"
                    if index in selected
                    else str(option)
                ),
                callback_data=f"verify:{session_row.id}:{index}",
            )
            for index, option in enumerate(options)
        ]
        rows.append(buttons[0:2])
        rows.append(buttons[2:4])
        if len(buttons) > 4:
            rows.append(buttons[4:6])
        if _is_multi_answer(session_row):
            rows.append(
                [
                    InlineKeyboardButton(
                        i18n.t("bot.button.verify.submit", locale=lang),
                        callback_data=f"verify:{session_row.id}:submit",
                    )
                ]
            )
    elif session_row.method == "emoji":
        buttons = [
            InlineKeyboardButton(
                str(option), callback_data=f"verify:{session_row.id}:{index}"
            )
            for index, option in enumerate(options)
        ]
        rows.append(buttons[0:3])
        rows.append(buttons[3:6])
    rows.append(_admin_row(session_row.id, lang))
    return InlineKeyboardMarkup(rows)
