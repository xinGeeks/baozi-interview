"""feedback.py 单元测试。

- parse_feedback_response:容错解析,各种边界
- build_feedback_prompt:snapshot,确认不含 resume/JD、含硬约束
"""
from __future__ import annotations

import pytest

from feedback import build_feedback_prompt, parse_feedback_response


# ============================================================================
# parse_feedback_response
# ============================================================================

class TestParseFeedbackResponse:
    def test_standard_two_lines(self):
        text = "【分数】7/10\n【建议】回答里缺少量化指标,补一个具体数字。"
        result = parse_feedback_response(text)
        assert result["score"] == 7
        assert "缺少量化指标" in result["advice"]

    def test_score_with_spaces(self):
        text = "【分数】  8  /  10\n【建议】具体。补项目。"
        result = parse_feedback_response(text)
        assert result["score"] == 8

    def test_advice_truncated_to_first_line(self):
        text = "【分数】6/10\n【建议】第一行建议。\n第二行废话。\n第三行更多废话。"
        result = parse_feedback_response(text)
        assert result["advice"] == "第一行建议。"

    def test_missing_score_defaults_to_5(self):
        text = "【建议】这是一段没有分数的建议。"
        result = parse_feedback_response(text)
        assert result["score"] == 5
        assert "没有分数" in result["advice"]

    def test_missing_advice_defaults_to_empty(self):
        text = "【分数】4/10"
        result = parse_feedback_response(text)
        assert result["score"] == 4
        assert result["advice"] == ""

    def test_strips_think_block(self):
        text = (
            "<think>让我评估一下这个回答</think>"
            "【分数】8/10\n【建议】回答流畅,逻辑清晰。"
        )
        result = parse_feedback_response(text)
        assert result["score"] == 8
        assert "<think>" not in result["advice"]
        assert "回答流畅" in result["advice"]

    @pytest.mark.parametrize("raw_score,expected", [(15, 10), (-3, 0), (5, 5)])
    def test_score_clamped_to_range(self, raw_score, expected):
        text = f"【分数】{raw_score}/10\n【建议】x"
        result = parse_feedback_response(text)
        assert result["score"] == expected


# ============================================================================
# build_feedback_prompt
# ============================================================================

class TestBuildFeedbackPrompt:
    @pytest.mark.parametrize(
        "level",
        ["校招", "实习", "社招(初级)", "社招(中级)", "社招(高级)", "社招(资深)"],
    )
    def test_includes_level(self, level):
        prompt = build_feedback_prompt(level, "自我介绍", "我做了 3 年后端")
        assert level in prompt

    def test_does_not_leak_resume_or_jd(self):
        prompt = build_feedback_prompt(
            "社招(中级)", "讲讲你的项目", "我做的是电商订单系统"
        )
        # 防止后续维护里不小心把 resume/JD 拼进来(那会引入"对齐 JD 给分"的偏差)
        assert "简历" not in prompt
        assert "JD" not in prompt
        assert "岗位" not in prompt

    def test_contains_hard_constraints(self):
        prompt = build_feedback_prompt("校招", "自我介绍", "我叫张三")
        # 硬约束关键词(v0.3 反虚高:把'拉开差距'换成'默认落 4-6'具体化)
        assert "大多数普通回答应落 4-6" in prompt or "大多数" in prompt
        assert "禁止" in prompt
        assert "套话" in prompt

    def test_contains_question_and_answer(self):
        prompt = build_feedback_prompt(
            "实习", "你最快什么时候入职", "两周后"
        )
        assert "你最快什么时候入职" in prompt
        assert "两周后" in prompt

    def test_format_strict_two_lines_explained(self):
        prompt = build_feedback_prompt("校招", "q", "a")
        assert "严格两行" in prompt
        assert "【分数】N/10" in prompt
        assert "【建议】" in prompt

    def test_anti_inflation_anchor_section_present(self):
        """反虚高锚定段必须存在(每档分数绑具体证据)。"""
        prompt = build_feedback_prompt("社招(中级)", "q", "a")
        assert "反虚高锚定" in prompt

    def test_default_anchor_is_5_not_7(self):
        """默认锚是 5(及格线),不是 6-7。这是 v0.3 打分校准的核心改动。"""
        prompt = build_feedback_prompt("校招", "q", "a")
        assert "5 分 = 默认" in prompt
        # 必须显式说"大多数普通回答应落 4-6"
        assert "4-6" in prompt or "大多数" in prompt

    def test_8_plus_requires_quantified_evidence(self):
        """8 分以上必须要求可量化成果 / 独特洞察,而不仅是『答得不错』。"""
        prompt = build_feedback_prompt("社招(高级)", "q", "a")
        assert "8 分" in prompt
        assert "量化" in prompt
        assert "9 分" in prompt  # 9 分的稀有性必须显式标注
        assert "极罕见" in prompt or "罕见" in prompt

    def test_7_plus_requires_evidence_or_drop_to_5(self):
        """想给 7+ 必须有证据,否则扣到 5。这条规则是反虚高的强制门。"""
        prompt = build_feedback_prompt("实习", "q", "a")
        assert "7+" in prompt or "7 分" in prompt
        assert "扣到 5" in prompt

    def test_low_score_requires_concrete_deduction_reason(self):
        """≤4 分必须能列出具体扣分点(防止 LLM 给低分时不解释)。"""
        prompt = build_feedback_prompt("校招", "q", "a")
        assert "≤4" in prompt or "4 分" in prompt
        assert "扣分点" in prompt