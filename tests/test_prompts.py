"""prompts.py 单元测试。

- 6 档 × 2 风格 = 12 组合的 system prompt 快照,防 prompt 无声漂移
- 报告 prompt 关键硬约束检查
- 边界:空简历 / 空 JD / 未知 level / 未知 style
"""
from __future__ import annotations

import pytest

from prompts import (
    END_SIGNAL,
    LEVELS,
    LEVEL_FOCUS,
    SINGLE_QUESTION_RULE,
    STYLES,
    STYLE_FOCUS,
    build_interviewer_system_prompt,
    build_report_prompt,
)


# ============================================================================
# 6 档 × 2 风格 = 12 组合快照测试
# ============================================================================

@pytest.mark.parametrize("level", LEVELS)
@pytest.mark.parametrize("style", STYLES)
def test_interviewer_prompt_contains_level_and_style(level, style):
    prompt = build_interviewer_system_prompt(level, style, "测试简历", "测试 JD")
    assert level in prompt, f"system prompt 应包含职级 {level}"
    assert style in prompt, f"system prompt 应包含风格 {style}"


@pytest.mark.parametrize("level", LEVELS)
@pytest.mark.parametrize("style", STYLES)
def test_interviewer_prompt_has_single_question_rule(level, style):
    prompt = build_interviewer_system_prompt(level, style, "", "")
    assert "一次只问一个问题" in prompt
    assert "禁止一次性输出多题" in prompt


@pytest.mark.parametrize("level", LEVELS)
@pytest.mark.parametrize("style", STYLES)
def test_interviewer_prompt_has_no_early_verdict_rule(level, style):
    prompt = build_interviewer_system_prompt(level, style, "", "")
    assert "不透露" in prompt or "不预判" in prompt
    assert "打分" in prompt or "评价" in prompt or "评级" in prompt


@pytest.mark.parametrize("level", LEVELS)
def test_interviewer_prompt_uses_level_specific_focus(level):
    """每个职级必须包含自己的提问方向(不能复用其他职级)。"""
    prompt = build_interviewer_system_prompt(level, "温和引导", "", "")
    # 抽取 LEVEL_FOCUS[level] 的前 20 字,确保出现在 prompt
    expected_substring = LEVEL_FOCUS[level][:20]
    assert expected_substring in prompt, (
        f"{level} 应包含自己的提问方向,但缺少 '{expected_substring}'"
    )


def test_interviewer_prompt_contains_resume_when_provided():
    prompt = build_interviewer_system_prompt("社招(中级)", "温和引导", "Python 5 年", "后端")
    assert "Python 5 年" in prompt


def test_interviewer_prompt_handles_empty_resume():
    prompt = build_interviewer_system_prompt("校招", "温和引导", "", "算法岗 JD")
    assert "未上传简历" in prompt


def test_interviewer_prompt_handles_empty_jd():
    prompt = build_interviewer_system_prompt("校招", "温和引导", "简历内容", "")
    assert "未填写 JD" in prompt


def test_interviewer_prompt_includes_end_signal():
    prompt = build_interviewer_system_prompt("校招", "温和引导", "", "")
    assert END_SIGNAL in prompt


# ============================================================================
# 异常输入
# ============================================================================

def test_interviewer_prompt_rejects_unknown_level():
    with pytest.raises(ValueError, match="未知职级"):
        build_interviewer_system_prompt("校招(天才)", "温和引导", "", "")


def test_interviewer_prompt_rejects_unknown_style():
    with pytest.raises(ValueError, match="未知风格"):
        build_interviewer_system_prompt("校招", "佛系面", "", "")


# ============================================================================
# 报告 prompt 约束
# ============================================================================

def test_report_prompt_contains_transcript():
    history = [
        {"role": "assistant", "content": "请介绍一下你自己"},
        {"role": "user", "content": "我叫张三,做了 3 年后端"},
    ]
    prompt = build_report_prompt("社招(中级)", "简历", "JD", history)
    assert "[面试官]: 请介绍一下你自己" in prompt
    assert "[候选人]: 我叫张三,做了 3 年后端" in prompt


def test_report_prompt_contains_six_dimensions():
    prompt = build_report_prompt("校招", "", "", [])
    for dim in ["岗位匹配度", "专业技术能力", "项目实战能力",
                "逻辑思维能力", "沟通表达能力", "职级适配度"]:
        assert dim in prompt, f"报告 prompt 应包含维度 {dim}"


def test_report_prompt_forbids_hiring_verdict():
    prompt = build_report_prompt("校招", "", "", [])
    # 显式禁止录用建议
    assert "录用建议" in prompt  # 在『不写』约束中提到
    assert "不写" in prompt or "拒绝" in prompt


def test_report_prompt_requires_scoring_evidence():
    prompt = build_report_prompt("校招", "", "", [])
    assert "打分依据" in prompt
    assert "引用" in prompt or "原话" in prompt


def test_report_prompt_forbids_score_clustering():
    """报告 prompt 必须显式禁止 7-8 分聚拢。"""
    prompt = build_report_prompt("校招", "", "", [])
    assert "7-8" in prompt or "全是 7-8" in prompt


def test_report_prompt_includes_level_in_scoring_section():
    """打分要绑定职级。"""
    prompt = build_report_prompt("社招(高级)", "", "", [])
    assert "社招(高级)" in prompt


def test_report_prompt_handles_empty_resume_and_jd():
    prompt = build_report_prompt("校招", "", "", [])
    assert "(未上传简历)" in prompt
    assert "(用户未填写 JD)" in prompt


def test_report_prompt_rejects_unknown_level():
    with pytest.raises(ValueError, match="未知职级"):
        build_report_prompt("外挂", "", "", [])


# ============================================================================
# 静态校验:LEVELS / STYLES / 焦点表必须对齐
# ============================================================================

def test_level_focus_covers_all_levels():
    for level in LEVELS:
        assert level in LEVEL_FOCUS
        assert len(LEVEL_FOCUS[level]) > 20


def test_style_focus_covers_all_styles():
    for style in STYLES:
        assert style in STYLE_FOCUS
        assert len(STYLE_FOCUS[style]) > 10


def test_six_levels_unique():
    assert len(LEVELS) == 6
    assert len(set(LEVELS)) == 6  # 无重复


# ============================================================================
# v0.3 Feature A:turn_feedback 联动报告段
# ============================================================================

def test_report_prompt_includes_turn_feedback_table():
    """传 turn_feedback 时,prompt 应包含『逐轮评分』表格段。"""
    feedback = [
        {"question": "自我介绍", "score": 7, "advice": "缺数据"},
        {"question": "讲讲项目", "score": 5, "advice": "模糊"},
    ]
    prompt = build_report_prompt(
        level="社招(中级)",
        resume="r",
        jd="j",
        chat_history=[
            {"role": "assistant", "content": "q1"},
            {"role": "user", "content": "a1"},
        ],
        turn_feedback=feedback,
    )
    assert "逐轮评分" in prompt
    assert "| 轮次 |" in prompt  # markdown 表头
    assert "| 1 |" in prompt
    assert "| 2 |" in prompt
    assert "7/10" in prompt
    assert "5/10" in prompt
    assert "缺数据" in prompt
    assert "天花板" in prompt  # 反虚高锚点说明


def test_report_prompt_without_feedback_omits_section():
    """不传 turn_feedback(向后兼容),prompt 不含逐轮评分段。"""
    prompt = build_report_prompt(
        level="校招",
        resume="r",
        jd="j",
        chat_history=[],
    )
    assert "逐轮评分" not in prompt

    prompt_with_none = build_report_prompt(
        level="校招",
        resume="r",
        jd="j",
        chat_history=[],
        turn_feedback=None,
    )
    assert "逐轮评分" not in prompt_with_none

    prompt_with_empty = build_report_prompt(
        level="校招",
        resume="r",
        jd="j",
        chat_history=[],
        turn_feedback=[],
    )
    assert "逐轮评分" not in prompt_with_empty
