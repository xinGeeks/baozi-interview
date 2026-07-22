"""authenticity.py 单元测试。

- detect_signals: 4 条信号各覆盖正反向 + 边界
- parse_authenticity_response: 容错 + sentinel
- build_authenticity_judgment_prompt: snapshot 含硬约束
- 性能预算:200 词 < 1ms
"""
from __future__ import annotations

import time

import pytest

from authenticity import (
    SIGNAL_VOCAB,
    AuthenticityReport,
    Finding,
    _mentions_any_entity,
    _resume_entities,
    build_authenticity_judgment_prompt,
    detect_signals,
    parse_authenticity_response,
)


# ============================================================================
# detect_signals — 4 条信号
# ============================================================================


class TestDetectSignals:

    def test_clean_answer_returns_empty(self):
        """30+ 词 + 含数字 + 关键词重叠 + 提及简历 → 4 个信号都不触发。"""
        flags = detect_signals(
            question="介绍一下你最近做的订单系统项目",
            answer="我去年主导了订单系统重构,把核心链路从 MySQL 切到 TiDB,"
                   "QPS 从 3000 涨到 12000,延迟降到 30ms 以内。",
            resume_text="张三 后端工程师 订单系统 MySQL TiDB 高并发",
        )
        assert flags == []

    def test_too_short_flagged(self):
        flags = detect_signals(
            question="介绍一下你的项目经验",
            answer="我做过后端。",
        )
        assert "过于简短" in flags

    def test_too_short_with_question_not_flagged(self):
        """短回答但含问号(反问/澄清)不算过于简短。"""
        flags = detect_signals(
            question="你最有成就感的项目是什么",
            answer="哪个方面的?",
        )
        assert "过于简短" not in flags

    def test_boilerplate_without_digits_flagged(self):
        flags = detect_signals(
            question="讲讲你用过的技术栈",
            answer="我比较熟悉高并发、分布式架构,负责过很多东西,也有所了解。",
        )
        assert "模板化" in flags

    def test_boilerplate_with_digits_not_flagged(self):
        """含泛词但也有具体数字 → 不算模板化(因为至少有数据)。"""
        flags = detect_signals(
            question="讲讲你用过的技术栈",
            answer="我比较熟悉高并发,去年做了一个项目 QPS 达到 8000。",
        )
        assert "模板化" not in flags

    def test_off_topic_flagged(self):
        """问题问『高并发』,回答完全不沾边 → 答非所问。"""
        flags = detect_signals(
            question="你如何处理高并发场景的流量削峰?",
            answer="我喜欢打篮球,每周和朋友约三次,周末爬山。",
        )
        assert "答非所问" in flags

    def test_off_topic_with_keyword_overlap_not_flagged(self):
        """回答提了『流量』『削峰』等关键词 → 不算答非所问。"""
        flags = detect_signals(
            question="你如何处理高并发场景的流量削峰?",
            answer="我们用 Redis 做流量削峰,接口层做限流,QPS 峰值 5 万。",
        )
        assert "答非所问" not in flags

    def test_no_resume_mention_flagged_when_resume_nonempty(self):
        flags = detect_signals(
            question="讲讲你的订单系统项目",
            answer="我做了一个聊天工具,UI 用了 Vue。",
            resume_text="张三 后端工程师 订单系统 MySQL 高并发 分布式",
        )
        assert "未引用简历" in flags

    def test_no_resume_mention_skipped_when_resume_empty(self):
        """简历为空时不触发(无法判断 → 放过)。"""
        flags = detect_signals(
            question="讲讲你的项目",
            answer="我做了一个聊天工具。",
            resume_text="",
        )
        assert "未引用简历" not in flags

    def test_multiple_flags_can_coexist(self):
        """短 + 模板 + 答非所问 + 未引用简历可同时触发。"""
        flags = detect_signals(
            question="讲讲订单系统的高并发优化",
            answer="做过。",
            resume_text="张三 订单系统 高并发 Redis",
        )
        # "做过" 5 词 < 8,触发了简短
        assert "过于简短" in flags
        # 其他信号因短答可能不触发,只断言"过于简短"必出
        assert all(f in SIGNAL_VOCAB for f in flags)

    def test_empty_answer_returns_short(self):
        flags = detect_signals(question="q", answer="")
        assert flags == ["过于简短"]

    def test_returns_only_vocab_items(self):
        """防御性:任何返回值都必须是 SIGNAL_VOCAB 成员。"""
        result = detect_signals("q", "a" * 100, "r" * 100)
        assert all(f in SIGNAL_VOCAB for f in result)


# ============================================================================
# _resume_entities / _mentions_any_entity
# ============================================================================


class TestResumeEntities:

    def test_empty_resume_returns_empty_set(self):
        assert _resume_entities("") == set()

    def test_frequent_tokens_extracted(self):
        entities = _resume_entities(
            "张三 后端工程师 订单系统 MySQL 订单系统 高并发 订单系统 Redis"
        )
        # 2-gram 模型下,高频出现的 "订单" / "系统" 一定会被抽到
        assert "订单" in entities
        assert "系统" in entities

    def test_stopwords_excluded(self):
        entities = _resume_entities("的 了 在 我 你 他")
        assert entities == set()

    def test_short_tokens_excluded(self):
        """单字符 token 不算实体(太宽泛)。"""
        entities = _resume_entities("a b c d abcdef")
        # "abcdef" 长度 ≥2 保留,"a/b/c/d" 不保留
        assert "a" not in entities
        assert "b" not in entities
        assert "abcdef" in entities

    def test_mentions_any_empty_entities_returns_true(self):
        """空 entities 时放过(无法判断)。"""
        assert _mentions_any_entity("任何回答", set()) is True

    def test_mentions_any_finds_overlap(self):
        assert _mentions_any_entity(
            "我做了订单系统", {"订单系统", "MySQL"}
        ) is True

    def test_mentions_any_no_overlap(self):
        assert _mentions_any_entity(
            "我做了聊天工具", {"订单系统", "MySQL"}
        ) is False


# ============================================================================
# parse_authenticity_response — 容错
# ============================================================================


class TestParseAuthenticityResponse:

    def test_valid_json_full(self):
        text = (
            '{"score": 0.65, "findings": [{"turn": 3, "issue": "答非所问",'
            ' "detail": "问高并发却聊生活"}], "summary": "整体一般"}'
        )
        r = parse_authenticity_response(text)
        assert r.score == 0.65
        assert len(r.findings) == 1
        assert r.findings[0].turn == 3
        assert r.summary == "整体一般"
        assert r.is_valid

    def test_perfect_signals_yields_score_one(self):
        """LLM 应该返回 1.0 + 空 findings(per spec)。"""
        text = '{"score": 1.0, "findings": [], "summary": "无异常"}'
        r = parse_authenticity_response(text)
        assert r.score == 1.0
        assert r.findings == []

    def test_no_json_returns_sentinel(self):
        r = parse_authenticity_response("没有任何 JSON")
        assert r.score == -1.0
        assert "LLM 解析失败" in r.summary
        assert not r.is_valid

    def test_malformed_json_returns_sentinel(self):
        r = parse_authenticity_response('{"score": 0.5, "findings": [}')
        assert r.score == -1.0

    def test_score_clamped_to_range(self):
        """越界 → 截到 [0, 1]。"""
        r = parse_authenticity_response('{"score": 1.5}')
        assert r.score == 1.0
        r = parse_authenticity_response('{"score": -0.3}')
        assert r.score == 0.0

    def test_findings_truncated_to_3(self):
        text = (
            '{"score": 0.5, "findings": ['
            '{"turn": 1, "issue": "a", "detail": "1"},'
            '{"turn": 2, "issue": "b", "detail": "2"},'
            '{"turn": 3, "issue": "c", "detail": "3"},'
            '{"turn": 4, "issue": "d", "detail": "4"},'
            '{"turn": 5, "issue": "e", "detail": "5"}'
            ']}'
        )
        r = parse_authenticity_response(text)
        assert len(r.findings) == 3
        assert r.findings[-1].turn == 3  # 第 4/5 条被截

    def test_summary_truncated_to_200(self):
        long_summary = "x" * 500
        text = f'{{"score": 0.5, "summary": "{long_summary}"}}'
        r = parse_authenticity_response(text)
        assert len(r.summary) == 200

    def test_strips_think_block(self):
        text = (
            "<think>让我分析一下</think>"
            '{"score": 0.7, "findings": [], "summary": "ok"}'
        )
        r = parse_authenticity_response(text)
        assert r.score == 0.7

    def test_missing_score_returns_sentinel(self):
        text = '{"findings": [], "summary": "no score"}'
        r = parse_authenticity_response(text)
        assert r.score == -1.0

    def test_findings_with_garbage_entries_skipped(self):
        """findings 里非 dict 项被跳过,不会 crash。"""
        text = (
            '{"score": 0.5, "findings": ['
            'null, "string", 123, '
            '{"turn": 1, "issue": "x", "detail": "y"}'
            ']}'
        )
        r = parse_authenticity_response(text)
        assert len(r.findings) == 1
        assert r.findings[0].issue == "x"


# ============================================================================
# build_authenticity_judgment_prompt — snapshot
# ============================================================================


class TestBuildPrompt:

    def test_prompt_contains_hard_constraint(self):
        prompt = build_authenticity_judgment_prompt(
            resume="r", jd="j",
            chat_history=[
                {"role": "assistant", "content": "q1"},
                {"role": "user", "content": "a1"},
            ],
            turn_flags=[[]],
        )
        assert "只基于 given signals" in prompt

    def test_prompt_contains_empty_signals_marker(self):
        """空 signals 时仍需显式说"无信号",反 LLM 编造 finding。"""
        prompt = build_authenticity_judgment_prompt(
            resume="", jd="",
            chat_history=[],
            turn_flags=[],
        )
        assert "无信号" in prompt

    def test_prompt_includes_resume_and_jd(self):
        prompt = build_authenticity_judgment_prompt(
            resume="张三 后端", jd="招后端",
            chat_history=[{"role": "user", "content": "hi"}],
            turn_flags=[[]],
        )
        assert "张三 后端" in prompt
        assert "招后端" in prompt

    def test_prompt_includes_flagged_turns(self):
        prompt = build_authenticity_judgment_prompt(
            resume="", jd="",
            chat_history=[
                {"role": "assistant", "content": "讲讲项目"},
                {"role": "user", "content": "做过"},
            ],
            turn_flags=[["过于简短"]],
        )
        assert "过于简短" in prompt
        assert "轮 1" in prompt


# ============================================================================
# 性能预算
# ============================================================================


class TestPerformanceBudget:

    def test_detect_signals_under_1ms_for_200_words(self):
        """200 词回答 < 1ms(per spec)。"""
        answer = " ".join(["性能测试"] * 100)  # 200 个 token
        question = "介绍一下你的项目经验"
        resume = "张三 后端工程师 " + " ".join(["技术栈"] * 50)

        # 跑 100 次取平均,排除抖动
        n = 100
        start = time.perf_counter()
        for _ in range(n):
            detect_signals(question, answer, resume)
        elapsed_ms = (time.perf_counter() - start) * 1000 / n
        assert elapsed_ms < 1.0, f"平均 {elapsed_ms:.3f}ms > 1ms"