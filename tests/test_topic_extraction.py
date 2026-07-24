"""topic_extraction.py 单元测试。

覆盖:
- CJK 2-gram tokenize(纯中文 / 纯英文 / 混合 / 空)
- PII mask(中文公司 / 英文公司后缀 / 项目代号 / case-insensitive)
- 同义词 fold
- 阈值过滤(min_tf / min_ratio)
- extract_topics 入口(正常 / 边界 / PII 不泄漏)
- 性能(<500ms / 30 turns × 200 words)
"""
from __future__ import annotations

import time

from topic_extraction import (
    DEFAULT_MIN_RATIO,
    DEFAULT_MIN_TF,
    TopicFact,
    _apply_synonyms,
    _compute_tf,
    _filter_by_thresholds,
    _mask_pii,
    _tokenize_cjk_2gram,
    extract_topics,
)


# ============================================================================
# _tokenize_cjk_2gram
# ============================================================================


def test_tokenize_pure_chinese_produces_2grams():
    toks = _tokenize_cjk_2gram("分布式系统")
    # "分布式系统" 5 chars → 4 个 bigrams: 分布, 布式, 式系, 系统
    assert "分布" in toks
    assert "系统" in toks
    assert len(toks) == 4


def test_tokenize_pure_english_uses_whitespace():
    toks = _tokenize_cjk_2gram("Redis Kafka MongoDB")
    assert toks == ["redis", "kafka", "mongodb"]


def test_tokenize_mixed_cjk_and_english():
    toks = _tokenize_cjk_2gram("用 Redis 做缓存")
    # 含中文 + 英文;英文保留整词,中文走 2-gram
    assert "redis" in toks
    assert "缓存" in toks


def test_tokenize_filters_stopword_bigram():
    toks = _tokenize_cjk_2gram("的了一定")
    # "的" 是 stopword,所有含"的"的 2-gram 应被过滤
    for t in toks:
        assert "的" not in t


def test_tokenize_filters_short_english_words():
    toks = _tokenize_cjk_2gram("I am a Go dev")
    # 单字母 "i", "a" 被过滤(长度 < 2); "am" 长度=2 保留(非 stopword);
    # "go" 是 stopword(泛义动词); "dev" 长度=2+ 非 stopword 保留
    assert "am" in toks
    assert "dev" in toks
    assert "go" not in toks  # by design: "go" 太通用,不算 content topic


def test_tokenize_empty_returns_empty():
    assert _tokenize_cjk_2gram("") == []
    assert _tokenize_cjk_2gram("   ") == []


# ============================================================================
# _mask_pii
# ============================================================================


def test_mask_chinese_company_suffix():
    masked = _mask_pii("我在百度公司做后端开发")
    assert "百度公司" not in masked
    # mask 后是空格,做后端开发 仍然保留
    assert "后端" in masked or "做后" in masked


def test_mask_chinese_group_suffix():
    masked = _mask_pii("在阿里巴巴集团工作")
    assert "阿里巴巴集团" not in masked


def test_mask_english_company_with_llc():
    masked = _mask_pii("Worked at Acme LLC for 3 years")
    assert "Acme LLC" not in masked
    assert "AcmeLLC" not in masked


def test_mask_english_company_with_inc_case_insensitive():
    masked = _mask_pii("Joined foo inc in 2020")
    assert "foo inc" not in masked.lower()


def test_mask_company_with_space_between_entity_and_chinese_suffix():
    masked = _mask_pii("我在 Acme 公司设计了系统")
    assert "Acme" not in masked
    assert "acme" not in masked.lower()


def test_mask_project_codename():
    masked = _mask_pii("我参与了项目代号 Phoenix 的开发")
    assert "Phoenix" not in masked
    assert "代号" not in masked


def test_mask_keeps_non_pii_text():
    text = "高性能分布式系统"
    masked = _mask_pii(text)
    # 没有 PII 触发,文本不变
    assert "高性能" in masked


# ============================================================================
# _apply_synonyms
# ============================================================================


def test_apply_synonyms_folds_chinese_to_english():
    toks = _apply_synonyms(["性能", "perf", "performance"])
    assert toks == ["performance", "performance", "performance"]


def test_apply_synonyms_folds_HA_variants():
    toks = _apply_synonyms(["HA", "高可用", "high availability"])
    assert toks == ["high_availability"] * 3


def test_apply_synonyms_folds_qps_tps_to_throughput():
    toks = _apply_synonyms(["QPS", "tps", "throughput"])
    assert toks == ["throughput"] * 3


def test_apply_synonyms_preserves_unmapped():
    toks = _apply_synonyms(["分布式", "redis", "kafka"])
    assert toks == ["distributed", "redis", "kafka"]


def test_apply_synonyms_empty():
    assert _apply_synonyms([]) == []


# ============================================================================
# _compute_tf
# ============================================================================


def test_compute_tf_basic():
    tf = _compute_tf(["a", "b", "a", "c", "a"])
    assert tf == {"a": 3, "b": 1, "c": 1}


def test_compute_tf_empty():
    assert _compute_tf([]) == {}


# ============================================================================
# _filter_by_thresholds
# ============================================================================


def test_filter_min_tf_cuts_low_frequency():
    tf = {"a": 5, "b": 2, "c": 1}
    out = _filter_by_thresholds(tf, total=10, min_tf=3, min_ratio=0.0)
    assert [t for t, _ in out] == ["a"]


def test_filter_min_ratio_cuts_low_ratio():
    # total=100, "a" 出 5 次 → ratio 0.05(边界), 0.04 过滤
    tf = {"a": 5, "b": 4}
    out = _filter_by_thresholds(tf, total=100, min_tf=1, min_ratio=0.05)
    assert [t for t, _ in out] == ["a"]


def test_filter_both_passing_returns_all_sorted():
    tf = {"a": 10, "b": 5, "c": 3}
    out = _filter_by_thresholds(tf, total=20, min_tf=3, min_ratio=0.05)
    # 按 tf DESC, topic ASC tiebreak
    assert out == [("a", 10), ("b", 5), ("c", 3)]


def test_filter_both_failing_returns_empty():
    tf = {"a": 1, "b": 1}
    out = _filter_by_thresholds(tf, total=10, min_tf=3, min_ratio=0.05)
    assert out == []


def test_filter_zero_total_returns_empty():
    assert _filter_by_thresholds({"a": 5}, total=0, min_tf=3, min_ratio=0.05) == []


# ============================================================================
# extract_topics (公共 API)
# ============================================================================


def test_extract_topics_happy_path_cjk():
    turns = [
        {"role": "assistant", "content": "q1"},
        {"role": "user", "content": "我设计了一个分布式锁,处理高并发"},
        {"role": "assistant", "content": "q2"},
        {"role": "user", "content": "分布式锁的核心是分布式共识"},
        {"role": "assistant", "content": "q3"},
        {"role": "user", "content": "我们用了 redis 做分布式锁"},
        {"role": "assistant", "content": "q4"},
        {"role": "user", "content": "分布式锁要考虑性能"},
    ]
    topics = extract_topics(turns)
    assert len(topics) >= 1
    for t in topics:
        assert 0 <= t.score <= 1
        assert isinstance(t.topic, str)


def test_extract_topics_mixed_cjk_and_english():
    turns = [
        {"role": "user", "content": "用 Redis 做缓存"}
        for _ in range(5)
    ]
    topics = extract_topics(turns)
    # "redis" 出现 5 次 / 5 (含 stopword 过滤) → 应通过 min_tf=3
    assert any(t.topic == "redis" for t in topics)


def test_extract_topics_empty_input_returns_empty():
    assert extract_topics([]) == []


def test_extract_topics_only_assistant_turns_returns_empty():
    turns = [{"role": "assistant", "content": "question"}]
    assert extract_topics(turns) == []


def test_extract_topics_empty_content_returns_empty():
    turns = [{"role": "user", "content": ""} for _ in range(5)]
    assert extract_topics(turns) == []


def test_extract_topics_synonyms_fold_occur_once_each():
    # 每个 term 只出现 1 次,不会过 min_tf=3
    turns = [
        {"role": "user", "content": "性能"}
        for _ in range(1)
    ]
    # 只有 1 turn, 总 token 数太少
    assert extract_topics(turns) == []


def test_extract_topics_threshold_filter_works():
    # "常见" 这种 stopword 占大头,filter 后应为空
    turns = [{"role": "user", "content": "的  的  的 了"}]
    assert extract_topics(turns) == []


def test_extract_topics_pii_entities_excluded_from_output():
    turns = [
        {"role": "user", "content": "在 FooCorp 公司做过订单系统"}
        for _ in range(5)
    ]
    topics = extract_topics(turns)
    topic_names = [t.topic for t in topics]
    assert "FooCorp" not in topic_names
    assert "foocorp" not in topic_names
    assert "公司" not in topic_names
    assert "Inc" not in topic_names
    assert "LLC" not in topic_names


def test_extract_topics_source_turn_is_first_occurrence():
    turns = [
        {"role": "assistant", "content": "q0"},
        {"role": "user", "content": "随便说点"},  # idx 1
        {"role": "assistant", "content": "q1"},
        {"role": "user", "content": "kafka kafka kafka"},  # idx 3
        {"role": "assistant", "content": "q2"},
        {"role": "user", "content": "kafka kafka kafka kafka kafka kafka"},  # idx 5
    ]
    topics = extract_topics(turns)
    kafka_topic = next((t for t in topics if t.topic == "kafka"), None)
    assert kafka_topic is not None
    # 最早 user turn 出现 kafka 是 idx 3
    assert kafka_topic.source_turn == 3


def test_extract_topics_returns_topic_fact_instances():
    turns = [
        {"role": "user", "content": f"redis 测试 {i}"}
        for i in range(5)
    ]
    topics = extract_topics(turns)
    for t in topics:
        assert isinstance(t, TopicFact)


# ============================================================================
# 性能
# ============================================================================


def test_extract_topics_performance_30_turns_200_words():
    # 构造 30 turns,每 turn 200 字,绝大多数是性能/分布式术语
    turns = []
    paragraph = "分布式系统 高可用架构 " * 30  # ~180 chars
    for _ in range(30):
        turns.append({"role": "assistant", "content": "question"})
        turns.append({"role": "user", "content": paragraph})
    start = time.perf_counter()
    topics = extract_topics(turns)
    elapsed = time.perf_counter() - start
    assert elapsed < 0.5, f"extract_topics took {elapsed:.3f}s, expected <0.5s"
    assert len(topics) >= 3


# ============================================================================
# 默认阈值常量
# ============================================================================


def test_default_thresholds_match_spec():
    assert DEFAULT_MIN_TF == 3
    assert DEFAULT_MIN_RATIO == 0.05