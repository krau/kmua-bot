"""验证 challenge 的纯构建逻辑: 常量、题目生成、文案与键盘。"""

from __future__ import annotations

import math
import random
import re
from collections.abc import Iterable

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


def _fraction(numerator: int, denominator: int) -> str:
    divisor = math.gcd(numerator, denominator)
    numerator //= divisor
    denominator //= divisor
    return str(numerator) if denominator == 1 else f"{numerator}/{denominator}"


def _distractors(correct: int | str, candidates: Iterable[int | str]) -> list[str]:
    """从候选中随机取 3 个与正确答案不同的干扰项。"""
    pool = [c for c in candidates if str(c) != str(correct)]
    random.shuffle(pool)
    return [str(c) for c in pool[:3]]


def _math_html(question: str) -> str:
    """把题目中的行内公式 $...$ 转为 rich 消息的 <tg-math> 标签。"""
    return re.sub(r"\$([^$]+)\$", r"<tg-math>\1</tg-math>", question)


def _calculus_challenge() -> dict:
    kind = random.choice(("derivative", "integral", "limit"))
    if kind == "derivative":
        a = random.randint(2, 5)
        n = random.randint(2, 4)
        x = random.choice((1, 2))
        answer = a * n * (x ** (n - 1))
        question = f"设 $f(x) = {a}x^{n}$, 求 $f'({x})$"
        candidates = {answer + d for d in (-3, -2, -1, 1, 2, 3, n, -n)} | {a * (x**n)}
    elif kind == "integral":
        n = random.randint(1, 3)
        k = random.randint(1, 3)
        answer = k
        question = f"$\\int_0^1 {k * (n + 1)}x^{n}\\,dx$"
        candidates = {k + d for d in (-3, -2, -1, 1, 2, 3)} | {
            k * (n + 1),
            k + n,
        }
    else:  # limit
        k = random.randint(2, 5)
        answer = k
        question = f"$\\lim_{{x\\to 0}}\\frac{{\\sin({k}x)}}{{x}}$"
        candidates = {k + d for d in (-3, -2, -1, 1, 2, 3)} | {k * 2}
    options = [str(answer), *_distractors(answer, candidates)]
    random.shuffle(options)
    return {"question": question, "answer": str(answer), "options": options}


def _linear_algebra_challenge() -> dict:
    kind = random.choice(
        (
            "invertible_criterion",
            "rank_nullity",
            "det_scale",
            "symmetric_eigen",
            "diagonalizable",
            "trace_eigen",
            "transpose_inverse",
            "null_space_domain",
            "positive_definite",
        )
    )
    if kind == "invertible_criterion":
        n = random.randint(2, 4)
        answer = random.choice(
            (
                "det(A) ≠ 0",
                "存在方阵 B 使 AB = BA = I",
                "A 的列向量线性无关",
                "0 不是 A 的特征值",
            )
        )
        wrong = ("det(A) = 0", "A 的元素均非零", "A 是对称矩阵", "A 的秩为 1")
        question = f'设 A 是 {n}×{n} 实矩阵, 则 "A 可逆" 的等价条件是'
        candidates = {answer, *wrong}
    elif kind == "rank_nullity":
        n = random.randint(4, 6)
        nullity = random.choice((2, 3))
        rank = n - nullity
        answer = str(nullity)
        question = f"设 A 是 {n}×{n} 矩阵, rank(A) = {rank}, 求 dim null(A)"
        candidates = {str(nullity + d) for d in range(-2, 3)} | {str(n), str(rank)}
    elif kind == "det_scale":
        n = random.randint(2, 4)
        c = random.randint(2, 3)
        answer = f"{c**n} det(A)"
        question = f"设 A 是 {n}×{n} 矩阵, 求 $\\det({c}A)$"
        candidates = {f"{m} det(A)" for m in (c * n, c, 1, c + 1, c**n + 1)} | {answer}
    elif kind == "symmetric_eigen":
        frames = [
            (
                "实对称矩阵 A 的特征值一定都是什么数?",
                "实数",
                ("纯虚数", "非负数", "互不相同"),
            ),
            (
                "实对称矩阵 A 一定可以正交对角化, 即存在正交矩阵 Q 使 $Q^T A Q$ 为",
                "对角矩阵",
                ("三角矩阵", "单位矩阵", "零矩阵"),
            ),
        ]
        question, answer, wrong = random.choice(frames)
        candidates = {answer, *wrong}
    elif kind == "diagonalizable":
        n = random.randint(2, 4)
        answer = random.choice(
            ("有 n 个线性无关的特征向量", "每个特征值的几何重数等于代数重数")
        )
        wrong = (
            "有 n 个特征值(含重数)",
            "A 可逆",
            "rank(A) = n",
            "A 的特征多项式无重根",
        )
        question = f"设 A 是 {n}×{n} 矩阵, A 可对角化的充要条件是"
        candidates = {answer, *wrong}
    elif kind == "trace_eigen":
        answer = random.choice(("特征值之和", "主对角线元素之和"))
        wrong = ("特征值之积", "所有元素之和", "行列式", "特征值之差")
        question = "方阵 A 的迹 tr(A) 等于"
        candidates = {answer, *wrong}
    elif kind == "transpose_inverse":
        frames = [
            ("设 A 可逆, 则 $(A^T)^{-1}$ 等于", "(A⁻¹)ᵀ", ("A⁻¹", "Aᵀ", "A")),
            ("设 A, B 可逆, 则 $(AB)^{-1}$ 等于", "B⁻¹A⁻¹", ("A⁻¹B⁻¹", "A⁻¹", "AB")),
        ]
        question, answer, wrong = random.choice(frames)
        candidates = {answer, *wrong}
    elif kind == "null_space_domain":
        frames = [
            (
                "设 A 是 m×n 实矩阵, 则 A 的零空间是哪个空间的子空间?",
                "Rⁿ 的子空间",
                ("Rᵐ 的子空间", "R 的子空间", "不是任何空间的子空间"),
            ),
            (
                "设 A 是 m×n 实矩阵, 则 A 的列空间是哪个空间的子空间?",
                "Rᵐ 的子空间",
                ("Rⁿ 的子空间", "R 的子空间", "不是任何空间的子空间"),
            ),
        ]
        question, answer, wrong = random.choice(frames)
        candidates = {answer, *wrong}
    else:
        frames = [
            (
                "实对称矩阵 A 正定的充要条件是其特征值",
                "全部大于 0",
                ("全部非负", "全部小于 0", "互不相同"),
            ),
            (
                "实对称矩阵 A 半正定的充要条件是其特征值",
                "全部非负",
                ("全部大于 0", "全部小于 0", "互不相同"),
            ),
            (
                "实对称矩阵 A 负定的充要条件是其特征值",
                "全部小于 0",
                ("全部非负", "全部大于 0", "互不相同"),
            ),
        ]
        question, answer, wrong = random.choice(frames)
        candidates = {answer, *wrong}
    options = [answer, *_distractors(answer, candidates)]
    random.shuffle(options)
    return {"question": question, "answer": answer, "options": options}


def _probability_challenge() -> dict:
    kind = random.choice(
        (
            "uniform_e",
            "uniform_var",
            "exp_e",
            "normal_prob",
            "binomial_e",
            "poisson_var",
            "var_scale",
            "monty_hall",
            "max_two_uniform",
            "chebyshev",
            "sum_expectation",
            "second_moment",
        )
    )
    if kind == "uniform_e":
        a = random.randint(1, 4)
        b = a + 2 * random.randint(2, 4)
        answer = (a + b) // 2
        question = f"设 $X \\sim U({a}, {b})$, 求 $E[X]$"
        candidates = {str(answer + d) for d in range(-3, 4)} | {str(a), str(b)}
    elif kind == "uniform_var":
        b = random.choice((4, 6, 12))
        answer = _fraction(b * b, 12)
        question = f"设 $X \\sim U(0, {b})$, 求 $Var(X)$"
        candidates = {"4/3", "3", "12", "1/3", "1/2", "2/3", "4", "9", "16"}
    elif kind == "exp_e":
        lam = random.choice((2, 3, 4))
        answer = _fraction(1, lam)
        question = f"设 $X \\sim Exp({lam})$, 求 $E[X]$"
        candidates = {"1/2", "1/3", "1/4", "1/5", "2/3", "1"}
    elif kind == "normal_prob":
        mu = random.randint(1, 5)
        sigma2 = random.choice((1, 4, 9))
        answer = "1/2"
        question = f"设 $X \\sim N({mu}, {sigma2})$, 求 $P(X \\le {mu})$"
        candidates = {"1/2", "1/3", "1/4", "2/3", "3/4"}
    elif kind == "binomial_e":
        n = random.choice((8, 10, 12))
        p = random.choice(("0.25", "0.5"))
        answer = _fraction(n * (5 if p == "0.25" else 10), 20)  # n*p
        question = f"设 $X \\sim B({n}, {p})$, 求 $E[X]$"
        candidates = {_fraction(2 * n + i, 4) for i in range(-8, 9, 2)} | {"2", "3"}
    elif kind == "poisson_var":
        lam = random.randint(2, 5)
        answer = str(lam)
        question = f"设 $X \\sim Poisson({lam})$, 求 $Var(X)$"
        candidates = {str(lam + d) for d in range(-2, 3)} | {str(lam * 2), "1"}
    elif kind == "var_scale":
        c = random.choice((2, 3))
        answer = str(3 * c * c)  # X~U(0,6), Var=3
        question = f"设 $X \\sim U(0, 6)$, 求 $Var({c}X)$"
        candidates = {"3", "6", "9", "12", "18", "27", "36"}
    elif kind == "monty_hall":
        n = random.choice((3, 4, 5))
        answer = _fraction(n - 1, n * (n - 2))
        question = f"蒙提霍尔问题: 共 {n} 扇门, 主持人打开一扇空门后, 换门中奖的概率"
        candidates = {_fraction(m - 1, m * (m - 2)) for m in (3, 4, 5)} | {
            "1/2",
            "1/3",
            "1/4",
        }
    elif kind == "max_two_uniform":
        k = random.choice((2, 3))
        answer = _fraction(k, k + 1)
        question = f"设 $X_1, \\ldots, X_{k} \\sim U(0,1)$ 独立, 求 $E[\\max(X_1, \\ldots, X_{k})]$"
        candidates = {_fraction(m, m + 1) for m in (2, 3, 4)} | {"1/2", "1/3", "5/6"}
    elif kind == "chebyshev":
        mu = 5
        sigma = random.choice((2, 3))
        k = random.choice((2, 3))
        answer = _fraction(1, k * k)
        question = (
            f"设 $E[X]={mu}$, $Var(X)={sigma * sigma}$, "
            f"用切比雪夫不等式估计 $P(|X-{mu}| \\ge {k * sigma})$ 的上界"
        )
        candidates = {"1/2", "1/3", "1/4", "1/8", "1/9", "2/3", "1/16"}
    elif kind == "sum_expectation":
        a = random.choice((0, 2, 4))
        b = a + random.choice((4, 6))
        lam = random.choice((2, 3))
        mean = (a + b) // 2  # U(a,b) 期望; a、b 同奇偶保证为整数
        answer = _fraction(mean * lam + 1, lam)  # + Exp(λ) 的 1/λ
        question = f"设 $X \\sim U({a},{b})$, $Y \\sim Exp({lam})$ 独立, 求 $E[X+Y]$"
        candidates = {"2", "7/3", "5/2", "8/3", "3", "4", "9/2", "11/3"}
    else:  # second_moment
        b = random.choice((3, 4, 6))
        answer = _fraction(b * b, 3)  # X~U(0,b): E[X^2] = b^2/3
        question = f"设 $X \\sim U(0, {b})$, 求 $E[X^2]$"
        candidates = {"3", "16/3", "12", "9", "6", "18", "27", "32/3", "4"}
    options = [answer, *_distractors(answer, candidates)]
    random.shuffle(options)
    return {"question": question, "answer": answer, "options": options}


def make_math_hard_challenge() -> dict:
    generator = random.choice(
        (_calculus_challenge, _linear_algebra_challenge, _probability_challenge)
    )
    return generator()


def make_challenge_payload(method: str, questions: list[dict]) -> dict:
    """按验证方式生成 challenge payload; 未知方式退回 custom_qa。"""
    if method == "math_easy":
        return make_math_challenge()
    if method == "math_hard":
        return make_math_hard_challenge()
    if method == "emoji":
        return make_emoji_challenge()
    if method == "sticker":
        return make_sticker_challenge()
    return make_qa_challenge(questions)


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
    if method == "math_easy":
        body = i18n.t("bot.msg.verify.challenge_math_easy", locale=lang).format(
            a=payload["a"],
            b=payload["b"],
            attempts=attempts_left,
            max=config.verify_max_attempts,
        )
    elif method == "math_hard":
        body = i18n.t("bot.msg.verify.challenge_math_hard", locale=lang).format(
            question=_math_html(payload["question"]),
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
    # 空行分隔题目区与次数/超时提示, 避免混排
    return mention_line + prefix + body + "\n\n" + timeout_hint


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
    if session_row.method in ("math_easy", "math_hard", "custom_qa"):
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
