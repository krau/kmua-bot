from collections import Counter
from dataclasses import dataclass
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
            print(
                "spacy model not installed, please run: python -m spacy download zh_core_web_sm"
            )
            _nlp = spacy.blank("zh")
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


def analyze_message(text: str) -> dict[str, Any]:
    """
    综合分析消息的所有特征

    Args:
        text: 输入文本

    Returns:
        完整的分析结果
    """
    features = extract_features(text)

    return {
        "text": text,
        "features": features,
        "intent": analyze_intent(features),
        "emotion": analyze_emotion(features),
        "topics": extract_topics(features),
        "complexity": calculate_complexity(features),
    }
