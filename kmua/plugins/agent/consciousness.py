from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import spacy
from spacy.tokens import Doc

_nlp = None


def get_nlp():
    global _nlp
    if _nlp is None:
        try:
            _nlp = spacy.load("zh_core_web_sm")
        except OSError:
            from spacy.cli.download import download

            download("zh_core_web_sm")
            _nlp = spacy.load("zh_core_web_sm")
    return _nlp


@dataclass
class MessageFeatures:
    # 基础信息
    text: str
    length: int
    sentence_count: int

    # 词性分析
    nouns: list[str]  # 名词
    verbs: list[str]  # 动词
    adjectives: list[str]  # 形容词
    adverbs: list[str]  # 副词

    # 命名实体
    entities: dict[str, list[str]]  # 实体类型 -> 实体列表

    # 依存关系
    subjects: list[str]  # 主语
    objects: list[str]  # 宾语

    # 情感特征
    sentiment_indicators: dict[str, list[str]]  # positive/negative/neutral

    # 疑问特征
    is_question: bool
    question_words: list[str]

    # 命令特征
    is_command: bool
    imperative_verbs: list[str]

    # 语气特征
    exclamation_count: int

    # 关键词
    keywords: list[tuple[str, float]]  # (词, 重要度分数)


def extract_features(text: str) -> MessageFeatures:
    """
    从文本中提取全面的特征

    Args:
        text: 输入文本

    Returns:
        MessageFeatures: 提取的特征对象
    """
    nlp = get_nlp()
    doc = nlp(text)

    # 基础信息
    sentences = list(doc.sents)
    length = len(text)
    sentence_count = len(sentences)

    # 词性分析
    nouns = [token.text for token in doc if token.pos_ == "NOUN"]
    verbs = [token.text for token in doc if token.pos_ == "VERB"]
    adjectives = [token.text for token in doc if token.pos_ == "ADJ"]
    adverbs = [token.text for token in doc if token.pos_ == "ADV"]

    # 命名实体
    entities: dict[str, list[str]] = {}
    for ent in doc.ents:
        if ent.label_ not in entities:
            entities[ent.label_] = []
        entities[ent.label_].append(ent.text)

    # 依存关系 - 提取主语和宾语
    subjects = []
    objects = []
    for token in doc:
        if token.dep_ in ("nsubj", "nsubjpass"):  # 主语
            subjects.append(token.text)
        elif token.dep_ in ("dobj", "iobj", "pobj"):  # 宾语
            objects.append(token.text)

    # 情感指示词
    sentiment_indicators = _extract_sentiment_indicators(doc)

    # 疑问特征
    question_words = [
        "什么",
        "为什么",
        "怎么",
        "如何",
        "哪",
        "谁",
        "哪里",
        "何时",
        "吗",
        "呢",
    ]
    found_question_words = [w for w in question_words if w in text]
    is_question = (
        bool(found_question_words)
        or text.strip().endswith("?")
        or text.strip().endswith("?")
    )

    # 命令特征
    imperative_verbs = _extract_imperative_verbs(doc)
    is_command = len(imperative_verbs) > 0 and not is_question

    # 语气特征
    exclamation_count = text.count("!") + text.count("!")

    # 关键词提取
    keywords = _extract_keywords(doc)

    return MessageFeatures(
        text=text,
        length=length,
        sentence_count=sentence_count,
        nouns=nouns,
        verbs=verbs,
        adjectives=adjectives,
        adverbs=adverbs,
        entities=entities,
        subjects=subjects,
        objects=objects,
        sentiment_indicators=sentiment_indicators,
        is_question=is_question,
        question_words=found_question_words,
        is_command=is_command,
        imperative_verbs=imperative_verbs,
        exclamation_count=exclamation_count,
        keywords=keywords,
    )


def _extract_sentiment_indicators(doc: Doc) -> dict[str, list[str]]:
    """提取情感指示词"""

    # 情感词典
    positive_words = {
        "喜欢",
        "爱",
        "好",
        "棒",
        "赞",
        "优秀",
        "开心",
        "快乐",
        "高兴",
        "幸福",
        "满意",
        "感谢",
        "谢谢",
    }
    negative_words = {
        "讨厌",
        "恨",
        "坏",
        "差",
        "糟",
        "难过",
        "伤心",
        "生气",
        "愤怒",
        "失望",
        "抱歉",
        "对不起",
    }

    positive = []
    negative = []
    neutral = []

    for token in doc:
        text = token.text
        if text in positive_words:
            positive.append(text)
        elif text in negative_words:
            negative.append(text)
        elif token.pos_ == "ADJ":  # 其他形容词视为中性
            neutral.append(text)

    return {
        "positive": positive,
        "negative": negative,
        "neutral": neutral,
    }


def _extract_imperative_verbs(doc: Doc) -> list[str]:
    """提取命令动词"""
    imperative_verbs = []

    for sent in doc.sents:
        tokens = list(sent)
        if tokens and tokens[0].pos_ == "VERB":
            imperative_verbs.append(tokens[0].text)

    return imperative_verbs


def _extract_keywords(doc: Doc, top_n: int = 5) -> list[tuple[str, float]]:
    """
    提取关键词（基于词频和词性）

    Args:
        doc: spaCy Doc 对象
        top_n: 返回前 N 个关键词

    Returns:
        [(词, 分数), ...] 按分数降序排列
    """
    # 只考虑名词、动词、形容词
    important_pos = {"NOUN", "VERB", "ADJ"}

    # 统计词频
    word_freq: Counter[str] = Counter()
    for token in doc:
        if token.pos_ in important_pos and not token.is_stop and len(token.text) > 1:
            word_freq[token.text] += 1

    # 计算分数（词频 * 词性权重）
    pos_weight = {"NOUN": 1.5, "VERB": 1.2, "ADJ": 1.0}
    word_scores: dict[str, float] = {}

    for token in doc:
        if token.pos_ in important_pos and not token.is_stop and len(token.text) > 1:
            weight = pos_weight.get(token.pos_, 1.0)
            word_scores[token.text] = word_freq[token.text] * weight

    # 排序并返回 top N
    sorted_words = sorted(word_scores.items(), key=lambda x: x[1], reverse=True)
    return sorted_words[:top_n]


def analyze_intent(features: MessageFeatures) -> dict[str, Any]:
    """
    基于特征分析消息意图

    Args:
        features: 消息特征

    Returns:
        意图分析结果
    """
    intent = {
        "type": "statement",  # statement, question, command, greeting, farewell, affection, hate
        "sub_types": [],
        "focus": None,
    }

    # 判断类型
    if features.is_question:
        intent["type"] = "question"
        intent["sub_types"].append("information_seeking")
    elif features.is_command:
        intent["type"] = "command"
        intent["sub_types"].append("request")

    greeting_words = {"你好", "嗨", "hi", "hello", "早", "晚安"}
    farewell_words = {"再见", "拜拜", "bye", "回见"}
    affection_words = {"拥抱", "抱抱", "贴贴", "摸摸", "亲亲", "爱你", "揉揉", "捏捏"}
    hate_words = {"讨厌你", "滚开", "去死", "烦死了"}

    text_lower = features.text.lower()
    if any(word in text_lower for word in greeting_words):
        intent["type"] = "greeting"
    elif any(word in text_lower for word in farewell_words):
        intent["type"] = "farewell"
    elif any(word in text_lower for word in affection_words):
        intent["type"] = "affection"
    elif any(word in text_lower for word in hate_words):
        intent["type"] = "hate"

    if features.keywords:
        intent["focus"] = features.keywords[0][0]

    return intent


def analyze_emotion(features: MessageFeatures) -> dict[str, Any]:
    """
    基于特征分析情感

    Args:
        features: 消息特征

    Returns:
        情感分析结果
    """
    positive_count = len(features.sentiment_indicators.get("positive", []))
    negative_count = len(features.sentiment_indicators.get("negative", []))

    # 计算情感分数 (-1 到 1)
    total_sentiment_words = positive_count + negative_count
    if total_sentiment_words > 0:
        sentiment_score = (positive_count - negative_count) / total_sentiment_words
    else:
        sentiment_score = 0.0

    # 加入语气特征的影响
    if features.exclamation_count > 0:
        sentiment_score *= 1 + features.exclamation_count * 0.1

    # 判断情感类型
    if sentiment_score > 0.3:
        valence = "positive"
    elif sentiment_score < -0.3:
        valence = "negative"
    else:
        valence = "neutral"

    # 判断强度
    intensity = "low"
    if abs(sentiment_score) > 0.6:
        intensity = "high"
    elif abs(sentiment_score) > 0.3:
        intensity = "medium"

    return {
        "valence": valence,  # positive, negative, neutral
        "score": sentiment_score,
        "intensity": intensity,  # low, medium, high
        "exclamation_count": features.exclamation_count,
    }


def extract_topics(features: MessageFeatures) -> list[str]:
    """
    提取消息主题

    Args:
        features: 消息特征

    Returns:
        主题列表
    """
    topics = []

    # 从实体中提取主题
    for _, entities in features.entities.items():
        topics.extend(entities)

    # 从关键词中提取主题
    for keyword, _ in features.keywords[:3]:  # 取前3个关键词
        if keyword not in topics:
            topics.append(keyword)

    return topics


def calculate_complexity(features: MessageFeatures) -> dict[str, Any]:
    """
    计算消息复杂度

    Args:
        features: 消息特征

    Returns:
        复杂度分析结果
    """
    # 平均句子长度
    avg_sentence_length = features.length / max(features.sentence_count, 1)

    # 词汇丰富度（不同词性的总数）
    vocab_diversity = len(
        set(features.nouns + features.verbs + features.adjectives + features.adverbs)
    )

    # 实体数量
    entity_count = sum(len(entities) for entities in features.entities.values())

    # 计算复杂度分数 (0-10)
    complexity_score = min(
        10,
        (
            (avg_sentence_length / 10) * 3
            + (vocab_diversity / 10) * 4
            + (entity_count / 5) * 3
        ),
    )

    # 判断复杂度等级
    if complexity_score < 3:
        level = "simple"
    elif complexity_score < 7:
        level = "moderate"
    else:
        level = "complex"

    return {
        "score": complexity_score,
        "level": level,
        "avg_sentence_length": avg_sentence_length,
        "vocab_diversity": vocab_diversity,
        "entity_count": entity_count,
    }


@dataclass
class DirectednessAnalysis:
    """指向性分析结果"""

    score: float  # 0-1, 指向 bot 的强度
    level: str  # low, medium, high
    indicators: dict[str, Any]  # 具体的指向性指标


def analyze_directedness(
    text: str,
    *,
    bot_name: str | None = None,
    bot_username: str | None = None,
    has_mention: bool = False,
    has_reply: bool = False,
    is_private: bool = False,
) -> DirectednessAnalysis:
    """
    分析消息指向 bot 的强度

    Args:
        text: 消息文本
        bot_name: bot 的名字（如 "kmua"）
        bot_username: bot 的用户名（如 "kmuav2bot"）
        has_mention: 是否包含 @ 提及
        has_reply: 是否回复 bot 的消息
        is_private: 是否私聊

    Returns:
        DirectednessAnalysis: 指向性分析结果
    """
    score = 0.0
    indicators = {
        "has_mention": has_mention,
        "has_reply": has_reply,
        "is_private": is_private,
        "name_mentioned": False,
        "username_mentioned": False,
        "direct_address": False,
        "imperative_to_bot": False,
        "question_to_bot": False,
    }

    # 1. 私聊天然具有高指向性
    if is_private:
        score += 0.8
        indicators["is_private"] = True

    # 2. @ 提及 - 最强的指向性信号
    if has_mention:
        score += 0.9
        indicators["has_mention"] = True

    # 3. 回复 bot 的消息
    if has_reply:
        score += 0.7
        indicators["has_reply"] = True

    # 4. 提及 bot 名字或用户名
    text_lower = text.lower()
    if bot_name and bot_name.lower() in text_lower:
        score += 0.6
        indicators["name_mentioned"] = True

    if bot_username:
        username_patterns = [
            f"@{bot_username.lower()}",
            bot_username.lower(),
        ]
        if any(pattern in text_lower for pattern in username_patterns):
            score += 0.7
            indicators["username_mentioned"] = True

    # 5. 直接称呼词（你、您、你们）
    direct_address_words = ["你", "您", "你们"]
    if any(word in text for word in direct_address_words):
        score += 0.3
        indicators["direct_address"] = True

    # 6. 提取特征进行深度分析
    features = extract_features(text)

    # 7. 命令式语句指向性
    if features.is_command:
        # 命令通常是针对 bot 的
        score += 0.5
        indicators["imperative_to_bot"] = True

        # 特定命令动词增强指向性
        command_verbs = {"帮", "给", "告诉", "说", "查", "找", "搜", "发", "显示", "看"}
        if any(verb in features.imperative_verbs for verb in command_verbs):
            score += 0.2

    # 8. 疑问句指向性
    if features.is_question:
        # 问句很可能是针对 bot 的
        score += 0.4
        indicators["question_to_bot"] = True

        # 特定疑问词增强指向性
        high_directness_questions = {"你", "您", "是不是", "能不能", "可以", "会不会"}
        if any(word in text for word in high_directness_questions):
            score += 0.2

    # 9. 情感互动词汇（亲密/敌对行为）
    affection_words = {"抱抱", "贴贴", "摸摸", "亲亲", "爱你", "揉揉", "捏捏", "拥抱"}
    hate_words = {"讨厌你", "滚开", "去死", "烦死了"}

    if any(word in text for word in affection_words | hate_words):
        score += 0.6

    # 10. 特定指向性短语
    directive_phrases = [
        "你好",
        "你在吗",
        "你是谁",
        "你叫什么",
        "听我说",
        "注意",
        "看这个",
    ]
    if any(phrase in text for phrase in directive_phrases):
        score += 0.3

    # 归一化分数到 0-1 范围
    score = min(1.0, score)

    # 确定指向性等级
    if score >= 0.7:
        level = "high"
    elif score >= 0.4:
        level = "medium"
    else:
        level = "low"

    return DirectednessAnalysis(
        score=score,
        level=level,
        indicators=indicators,
    )


def calculate_directedness_simple(
    text: str,
    bot_name: str | None = None,
    has_mention: bool = False,
    has_reply: bool = False,
    is_private: bool = False,
) -> float:
    """
    简化版指向性计算，只返回分数

    Args:
        text: 消息文本
        bot_name: bot 的名字
        has_mention: 是否 @ 提及
        has_reply: 是否回复 bot
        is_private: 是否私聊

    Returns:
        float: 0-1 的指向性分数
    """
    result = analyze_directedness(
        text,
        bot_name=bot_name,
        has_mention=has_mention,
        has_reply=has_reply,
        is_private=is_private,
    )
    return result.score


@dataclass
class AnalyzedMessage:
    text: str
    features: MessageFeatures
    intent: dict[str, Any]
    emotion: dict[str, Any]
    topics: list[str]
    complexity: dict[str, Any]


def analyze_message(text: str) -> AnalyzedMessage:
    """
    综合分析消息的所有特征

    Args:
        text: 输入文本

    Returns:
        完整的分析结果
    """
    features = extract_features(text)
    return AnalyzedMessage(
        text=text,
        features=features,
        intent=analyze_intent(features),
        emotion=analyze_emotion(features),
        topics=extract_topics(features),
        complexity=calculate_complexity(features),
    )


@dataclass
class MessageAttention:
    attention: float
    message: AnalyzedMessage
    timestamp: datetime


def calculate_attention(result: AnalyzedMessage) -> float:
    """
    计算一条消息的注意力
    0 ~ 1
    """
    # [TODO] 太简陋了有点, 后续改进
    attention = 0.0
    # 情感强度贡献
    intensity_map = {"low": 0.1, "medium": 0.3, "high": 0.5}
    attention += intensity_map.get(result.emotion["intensity"], 0.0)
    # 复杂度贡献
    complexity_map = {"simple": 0.1, "moderate": 0.3, "complex": 0.5}
    attention += complexity_map.get(result.complexity["level"], 0.0)
    # 关键词数量贡献
    keyword_count = len(result.features.keywords)
    attention += min(0.2, keyword_count * 0.05)
    # 意图贡献
    if result.intent["type"] in ("affection", "hate"):
        attention += 0.2
    # 主题贡献
    topic_count = len(result.topics)
    attention += min(0.2, topic_count * 0.05)
    # 命令/疑问贡献
    if result.intent["type"] in ("command", "question"):
        attention += 0.2
    # 指向性贡献
    directedness_score = calculate_directedness_simple(result.text)
    attention += directedness_score * 0.3
    return min(attention, 1.0)


event_buffers: dict[str, deque[MessageAttention]] = defaultdict(
    lambda: deque(maxlen=20)
)


def ingest_message(chat_id: str, text: str, timestamp: float):
    analysis = analyze_message(text)
    attention_score = calculate_attention(analysis)
    message_attention = MessageAttention(
        attention=attention_score,
        message=analysis,
        timestamp=datetime.fromtimestamp(timestamp),
    )
    event_buffers[chat_id].append(message_attention)


def detect_event(key: str, n: int, threshold: float) -> list[MessageAttention] | None:
    buffer = event_buffers[key]
    if len(buffer) < n:
        return None
    recent = list(buffer)[-n:]
    avg_attention = sum(m.attention for m in recent) / len(recent)
    if avg_attention >= threshold:
        buffer.clear()
        return recent
    return None


@dataclass
class GlobalPerceptionState:
    # 互动形态
    message_volume: float  # 活跃度
    question_pressure: float  # 被提问的强度
    directedness: float  # 指向我的程度

    # 情绪气候
    emotional_intensity: float
    emotional_valence: float  # 正 / 负

    # 主题气候
    dominant_topics: dict[str, float]

    # 认知负荷
    complexity: float  # 话题复杂度


_global_state = GlobalPerceptionState(
    message_volume=0.5,
    question_pressure=0.3,
    directedness=0.4,
    emotional_intensity=0.2,
    emotional_valence=0.1,
    dominant_topics={},
    complexity=0.4,
)


def reset_global_state():
    global _global_state
    _global_state = GlobalPerceptionState(
        message_volume=0.5,
        question_pressure=0.3,
        directedness=0.4,
        emotional_intensity=0.2,
        emotional_valence=0.1,
        dominant_topics={},
        complexity=0.4,
    )


def update_global_state_by_event(event_messages: list[MessageAttention]):
    """
    根据一组事件消息更新全局感知状态
    """
    if not event_messages:
        return

    # 更新互动形态
    avg_attention = sum(m.attention for m in event_messages) / len(event_messages)
    _global_state.message_volume = min(
        1.0, _global_state.message_volume + avg_attention * 0.1
    )
    question_count = sum(
        1 for m in event_messages if m.message.intent["type"] == "question"
    )
    _global_state.question_pressure = min(
        1.0,
        _global_state.question_pressure + (question_count / len(event_messages)) * 0.1,
    )

    # 更新情绪气候
    avg_emotion_score = sum(m.message.emotion["score"] for m in event_messages) / len(
        event_messages
    )
    _global_state.emotional_intensity = min(
        1.0, _global_state.emotional_intensity + abs(avg_emotion_score) * 0.1
    )
    _global_state.emotional_valence = max(
        -1.0, min(1.0, _global_state.emotional_valence + avg_emotion_score * 0.1)
    )

    # 更新主题气候
    topic_counter: Counter[str] = Counter()
    for m in event_messages:
        for topic in m.message.topics:
            topic_counter[topic] += 1
    total_topics = sum(topic_counter.values())
    if total_topics > 0:
        _global_state.dominant_topics = {
            topic: count / total_topics for topic, count in topic_counter.items()
        }

    # 更新认知负荷
    avg_complexity = sum(m.message.complexity["score"] for m in event_messages) / len(
        event_messages
    )
    _global_state.complexity = min(
        1.0, _global_state.complexity + (avg_complexity / 10) * 0.1
    )

    # 更新指向性
    avg_directedness = sum(
        calculate_directedness_simple(m.message.text) for m in event_messages
    ) / len(event_messages)
    _global_state.directedness = min(
        1.0, _global_state.directedness + avg_directedness * 0.1
    )


def describe_level(value: float) -> str:
    if value < 0.3:
        return "low"
    elif value < 0.7:
        return "medium"
    else:
        return "high"


def build_impression_input() -> dict[str, Any]:
    return {
        "activity": describe_level(_global_state.message_volume),
        "pressure": _global_state.question_pressure,
        "emotional_climate": {
            "intensity": _global_state.emotional_intensity,
            "valence": _global_state.emotional_valence,
        },
        "themes": [
            topic
            for topic, _ in sorted(
                _global_state.dominant_topics.items(), key=lambda x: x[1], reverse=True
            )[:5]  # top 5
        ],
    }
