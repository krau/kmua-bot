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
    return attention


event_buffers: dict[str, deque[MessageAttention]] = defaultdict(
    lambda: deque(maxlen=50)
)


def ingest_message(chat_id: str, text: str, timestamp: float):
    """Ingest a message into the event buffer

    Arguments:
        key -- chat_id
        text -- message text
        timestamp -- message timestamp
    """
    analysis = analyze_message(text)
    attention_score = calculate_attention(analysis)
    message_attention = MessageAttention(
        attention=attention_score,
        message=analysis,
        timestamp=datetime.fromtimestamp(timestamp),
    )
    event_buffers[chat_id].append(message_attention)


def detect_event(
    chat_id: str, n: int, threshold: float
) -> list[MessageAttention] | None:
    """detect event from recent messages
    if average attention of last n messages >= threshold, return the messages and **clear the buffer**

    Arguments:
        chat_id -- _chat_id_
        n -- number of messages to consider
        threshold --attention threshold

    Returns:
        list[MessageAttention] | None
    """
    buffer = event_buffers[chat_id]
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

    # 疲劳度和新鲜度
    fatigue: float  # 疲劳程度
    novelty_decay: float  # 新鲜度衰减

    def copy(self) -> "GlobalPerceptionState":
        """创建当前状态的深拷贝"""
        return GlobalPerceptionState(
            message_volume=self.message_volume,
            question_pressure=self.question_pressure,
            directedness=self.directedness,
            emotional_intensity=self.emotional_intensity,
            emotional_valence=self.emotional_valence,
            dominant_topics=self.dominant_topics.copy(),
            complexity=self.complexity,
            fatigue=self.fatigue,
            novelty_decay=self.novelty_decay,
        )

    def diff(self, previous: "GlobalPerceptionState") -> dict[str, Any]:
        """计算与之前状态的差异"""
        return {
            "message_volume": {
                "previous": previous.message_volume,
                "current": self.message_volume,
                "change": self.message_volume - previous.message_volume,
            },
            "question_pressure": {
                "previous": previous.question_pressure,
                "current": self.question_pressure,
                "change": self.question_pressure - previous.question_pressure,
            },
            "directedness": {
                "previous": previous.directedness,
                "current": self.directedness,
                "change": self.directedness - previous.directedness,
            },
            "emotional_intensity": {
                "previous": previous.emotional_intensity,
                "current": self.emotional_intensity,
                "change": self.emotional_intensity - previous.emotional_intensity,
            },
            "emotional_valence": {
                "previous": previous.emotional_valence,
                "current": self.emotional_valence,
                "change": self.emotional_valence - previous.emotional_valence,
            },
            "complexity": {
                "previous": previous.complexity,
                "current": self.complexity,
                "change": self.complexity - previous.complexity,
            },
            "fatigue": {
                "previous": previous.fatigue,
                "current": self.fatigue,
                "change": self.fatigue - previous.fatigue,
            },
            "novelty_decay": {
                "previous": previous.novelty_decay,
                "current": self.novelty_decay,
                "change": self.novelty_decay - previous.novelty_decay,
            },
        }


_global_state = GlobalPerceptionState(
    message_volume=0.5,
    question_pressure=0.3,
    directedness=0.4,
    emotional_intensity=0.2,
    emotional_valence=0.1,
    dominant_topics={},
    complexity=0.4,
    fatigue=0.2,
    novelty_decay=0.5,
)

# 上次发布贴文时的状态快照
_last_post_snapshot: GlobalPerceptionState | None = None


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
        fatigue=0.2,
        novelty_decay=0.5,
    )


def update_global_state_by_event(event_messages: list[MessageAttention]):
    """
    根据一组事件消息更新全局感知状态
    采用加权平滑更新，避免值一直增长
    """
    if not event_messages:
        return

    # 平滑系数：新数据权重
    alpha = 0.3

    # 更新互动形态 - 使用加权平均
    avg_attention = sum(m.attention for m in event_messages) / len(event_messages)
    _global_state.message_volume = (
        alpha * avg_attention + (1 - alpha) * _global_state.message_volume
    )

    question_count = sum(
        1 for m in event_messages if m.message.intent["type"] == "question"
    )
    question_ratio = question_count / len(event_messages)
    _global_state.question_pressure = (
        alpha * question_ratio + (1 - alpha) * _global_state.question_pressure
    )

    # 更新情绪气候 - 使用加权平均
    avg_emotion_score = sum(m.message.emotion["score"] for m in event_messages) / len(
        event_messages
    )
    avg_emotion_intensity = sum(
        {"low": 0.2, "medium": 0.5, "high": 0.8}.get(
            m.message.emotion["intensity"], 0.5
        )
        for m in event_messages
    ) / len(event_messages)

    _global_state.emotional_intensity = (
        alpha * avg_emotion_intensity + (1 - alpha) * _global_state.emotional_intensity
    )
    _global_state.emotional_valence = (
        alpha * avg_emotion_score + (1 - alpha) * _global_state.emotional_valence
    )
    # 限制在 [-1, 1] 范围内
    _global_state.emotional_valence = max(
        -1.0, min(1.0, _global_state.emotional_valence)
    )

    # 更新主题气候 - 合并旧主题和新主题
    topic_counter: Counter[str] = Counter()
    for m in event_messages:
        for topic in m.message.topics:
            topic_counter[topic] += 1

    # 衰减旧主题
    decay_factor = 0.7
    for topic in list(_global_state.dominant_topics.keys()):
        _global_state.dominant_topics[topic] *= decay_factor

    # 添加新主题
    total_topics = sum(topic_counter.values())
    if total_topics > 0:
        for topic, count in topic_counter.items():
            new_weight = count / total_topics
            if topic in _global_state.dominant_topics:
                _global_state.dominant_topics[topic] = (
                    alpha * new_weight
                    + (1 - alpha) * _global_state.dominant_topics[topic]
                )
            else:
                _global_state.dominant_topics[topic] = new_weight * alpha

    # 清理权重太低的主题
    _global_state.dominant_topics = {
        topic: weight
        for topic, weight in _global_state.dominant_topics.items()
        if weight > 0.05
    }

    # 更新认知负荷 - 使用加权平均
    avg_complexity = sum(m.message.complexity["score"] for m in event_messages) / len(
        event_messages
    )
    normalized_complexity = avg_complexity / 10  # 归一化到 0-1
    _global_state.complexity = (
        alpha * normalized_complexity + (1 - alpha) * _global_state.complexity
    )

    # 更新指向性 - 使用加权平均
    avg_directedness = sum(
        calculate_directedness_simple(m.message.text) for m in event_messages
    ) / len(event_messages)
    _global_state.directedness = (
        alpha * avg_directedness + (1 - alpha) * _global_state.directedness
    )

    # 更新疲劳度 - 基于活跃度和问题压力增加，同时有自然恢复
    fatigue_increase = (
        _global_state.message_volume * 0.1 + _global_state.question_pressure * 0.15
    )
    fatigue_recovery = 0.05  # 自然恢复
    _global_state.fatigue = max(
        0.0, min(1.0, _global_state.fatigue + fatigue_increase - fatigue_recovery)
    )

    # 新鲜度 - 重复主题降低新鲜度，新主题增加新鲜度
    if _global_state.dominant_topics:
        max_topic_freq = max(_global_state.dominant_topics.values())
        # 高频主题降低新鲜度
        novelty_decrease = max_topic_freq * 0.1
        # 新主题数量增加新鲜度
        new_topics = len(
            [t for t in topic_counter.keys() if t not in _global_state.dominant_topics]
        )
        novelty_increase = min(0.1, new_topics * 0.02)

        _global_state.novelty_decay = max(
            0.0,
            min(1.0, _global_state.novelty_decay - novelty_decrease + novelty_increase),
        )
    else:
        # 无主题时新鲜度缓慢恢复
        _global_state.novelty_decay = min(1.0, _global_state.novelty_decay + 0.02)


def describe_level(value: float) -> str:
    """将 0-1 的值转换为描述性文字"""
    if value < 0.3:
        return "低"
    elif value < 0.7:
        return "中"
    else:
        return "高"


def describe_valence(value: float) -> str:
    """描述情感倾向"""
    if value > 0.3:
        return "积极"
    elif value < -0.3:
        return "消极"
    else:
        return "中性"


def build_impression_input() -> dict[str, Any]:
    """
    构建当前全局感知状态的结构化输入，用于生成贴文
    """
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
        "fatigue": _global_state.fatigue,
        "novelty": _global_state.novelty_decay,
    }


def get_global_state() -> GlobalPerceptionState:
    """获取全局感知状态"""
    return _global_state


def get_last_snapshot() -> GlobalPerceptionState | None:
    """获取上次快照"""
    return _last_post_snapshot


def create_snapshot() -> GlobalPerceptionState:
    """创建并保存当前状态的快照"""
    global _last_post_snapshot
    _last_post_snapshot = _global_state.copy()
    return _last_post_snapshot


def get_state_changes() -> dict[str, Any] | None:
    """获取自上次快照以来的状态变化"""
    if _last_post_snapshot is None:
        return None
    return _global_state.diff(_last_post_snapshot)


def generate_post_prompt() -> str:
    """
    根据全局感知状态生成贴文提示词

    Returns:
        str: 给 AI 的提示词
    """
    state = _global_state

    # 构建描述
    activity_desc = describe_level(state.message_volume)
    emotion_desc = describe_valence(state.emotional_valence)
    intensity_desc = describe_level(state.emotional_intensity)
    complexity_desc = describe_level(state.complexity)
    fatigue_desc = describe_level(state.fatigue)
    novelty_desc = describe_level(state.novelty_decay)

    # 获取热门主题
    top_topics = sorted(
        state.dominant_topics.items(), key=lambda x: x[1], reverse=True
    )[:10]
    topics_str = "、".join([t[0] for t in top_topics]) if top_topics else "无特别主题"

    prompt = f"""根据你最近一段时间的观察和体验，写一条简短的个人感想贴文。

当前感知状态：
- 互动活跃度: {activity_desc} ({state.message_volume:.2f})
- 被提问压力: {describe_level(state.question_pressure)} ({state.question_pressure:.2f})
- 指向你的程度: {describe_level(state.directedness)} ({state.directedness:.2f})
- 情绪氛围: {emotion_desc}，强度{intensity_desc} (倾向值: {state.emotional_valence:.2f}, 强度: {state.emotional_intensity:.2f})
- 话题复杂度: {complexity_desc} ({state.complexity:.2f})
- 热门主题: {topics_str}
- 疲劳程度: {fatigue_desc} ({state.fatigue:.2f})
- 新鲜感: {novelty_desc} ({state.novelty_decay:.2f})"""

    # 添加状态变化信息
    changes = get_state_changes()
    if changes:
        prompt += "\n\n自上次贴文以来的变化："

        def format_change(name: str, data: dict) -> str:
            change = data["change"]
            if abs(change) < 0.05:
                return f"- {name}: 基本保持稳定"
            direction = "增加" if change > 0 else "减少"
            magnitude = "显著" if abs(change) > 0.2 else "略有"
            return f"- {name}: {magnitude}{direction} ({change:+.2f})"

        prompt += "\n" + format_change("活跃度", changes["message_volume"])
        prompt += "\n" + format_change("问题压力", changes["question_pressure"])
        prompt += "\n" + format_change("情绪倾向", changes["emotional_valence"])
        prompt += "\n" + format_change("疲劳度", changes["fatigue"])
        prompt += "\n" + format_change("新鲜感", changes["novelty_decay"])
    else:
        prompt += "\n\n（这是第一次发布贴文）"

    prompt += "\n\n现在，请根据以上感知状态和变化趋势，写一条贴文："

    return prompt
