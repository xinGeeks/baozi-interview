"""pages/interview.py 集成测试 (Streamlit AppTest)。

覆盖:
- 渲染:对话历史 / chat_input / 反馈卡 / 结束按钮
- 启动:pending_start + auto-start 链路
- 交互:提交回答 → 反馈 + 追问
- 结束:END_SIGNAL / 显式结束按钮 → generation_report + 跳报告页
- practice mode:不同标题 / 退出按钮 / 退出专项训练 文本信号
- 错误处理:LLMError 透传到 error_msg
- 预占:未开始 → 引导回 config + st.stop()
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from prompts import END_SIGNAL
from storage import init_db, save_session
from tests.conftest import FakeLLM


# ============================================================================
# 工具
# ============================================================================


def _interview(
    db_path: Path,
    *,
    interview_started: bool = True,
    practice_mode: bool = False,
    practice_topic: str = "",
    chat_history: list[dict] | None = None,
    turn_feedback: list[dict] | None = None,
    turn_authenticity_flags: list[list[str]] | None = None,
    mock_responses: list[str] | None = None,
    mock_feedback: list[str] | None = None,
    jd_content: str = "JD",
    interview_level: str = "社招(中级)",
    interview_style: str = "温和引导",
    timeout: int = 60,
) -> AppTest:
    """构造 AppTest 指向 interview page,绑独立 DB + 注入状态。

    默认 interview_started=True,跳过 pending_start auto-start 链路(更适合
    测 chat loop 本身)。要测 auto-start 单独走 pending_start 路径。
    """
    os.environ["STORAGE_DB_PATH"] = str(db_path)
    init_db(db_path)
    at = AppTest.from_file("app.py", default_timeout=timeout)
    at.run()
    at.switch_page("pages/interview.py")
    at.session_state["interview_started"] = interview_started
    at.session_state["practice_mode"] = practice_mode
    at.session_state["practice_topic"] = practice_topic
    at.session_state["chat_history"] = chat_history or []
    at.session_state["turn_feedback"] = turn_feedback or []
    at.session_state["turn_authenticity_flags"] = turn_authenticity_flags or []
    at.session_state["jd_content"] = jd_content
    at.session_state["interview_level"] = interview_level
    at.session_state["interview_style"] = interview_style
    if mock_responses is not None:
        at.session_state["mock_responses"] = list(mock_responses)
    if mock_feedback is not None:
        at.session_state["mock_feedback_responses"] = list(mock_feedback)
    at.run()
    return at


def _button_by_label(at: AppTest, needle: str):
    for b in at.button:
        if needle in str(b.label or ""):
            return b
    return None


# ============================================================================
# 渲染
# ============================================================================


class TestInterviewPageRender:
    def test_normal_title_renders(self, tmp_path: Path):
        at = _interview(tmp_path / "test.db")
        titles = [t.value for t in at.title]
        assert any("面试对话" in t for t in titles), (
            f"期望『面试对话』标题,实际: {titles}"
        )

    def test_practice_title_renders(self, tmp_path: Path):
        at = _interview(
            tmp_path / "test.db",
            practice_mode=True,
            practice_topic="kafka",
        )
        titles = [t.value for t in at.title]
        assert any("专项训练" in t for t in titles), (
            f"practice 应显示『专项训练』标题,实际: {titles}"
        )
        captions = [c.value for c in at.caption]
        assert any("kafka" in c for c in captions), (
            f"practice 应显示焦点主题,实际: {captions}"
        )

    def test_normal_shows_end_button(self, tmp_path: Path):
        at = _interview(tmp_path / "test.db")
        btn = _button_by_label(at, "结束面试")
        assert btn is not None, "正常模式应显示结束面试按钮"

    def test_practice_shows_exit_button(self, tmp_path: Path):
        at = _interview(
            tmp_path / "test.db",
            practice_mode=True,
            practice_topic="kafka",
        )
        btn = _button_by_label(at, "退出专项训练")
        assert btn is not None, "practice 模式应显示退出专项训练按钮"
        # 不应再显示结束面试按钮
        assert _button_by_label(at, "结束面试") is None

    def test_chat_input_present(self, tmp_path: Path):
        at = _interview(tmp_path / "test.db")
        assert len(at.chat_input) == 1, "进行中应显示 chat_input"

    def test_caption_shows_level_and_style(self, tmp_path: Path):
        at = _interview(
            tmp_path / "test.db",
            interview_level="社招(高级)",
            interview_style="压力深挖",
        )
        captions = [c.value for c in at.caption]
        text = "\n".join(captions)
        assert "社招(高级)" in text and "压力深挖" in text, (
            f"caption 应含等级 + 风格,实际: {text}"
        )


# ============================================================================
# 未开始状态
# ============================================================================


class TestNotStarted:
    def test_not_started_shows_redirect_info(self, tmp_path: Path):
        """未开始时,引导回 config 页 + 不渲染 chat_input。"""
        at = _interview(tmp_path / "test.db", interview_started=False)
        # 引导信息(info 元素)
        info_text = "\n".join(i.value for i in at.info)
        assert "配置" in info_text, (
            f"期望引导回 config,实际: {info_text[:300]}"
        )
        # 不应渲染 chat_input
        assert len(at.chat_input) == 0, "未开始不应有 chat_input"

    def test_not_started_redirect_button_uses_request_nav(self, tmp_path: Path):
        """未开始 → 点『去配置页』→ 触发 request_nav('config')。"""
        at = _interview(tmp_path / "test.db", interview_started=False)
        btn = _button_by_label(at, "去配置页")
        assert btn is not None
        btn.click()
        at.run()
        # request_nav → rerun → _consume_nav 已消费 → 当前 page 应为 config
        assert at.session_state["current_page"] == "config", (
            f"期望 current_page='config',实际: "
            f"{at.session_state.get('current_page')!r}"
        )


# ============================================================================
# 启动:pending_start → auto-start
# ============================================================================


class TestPendingStartAutoStart:
    def test_pending_start_runs_first_question(self, tmp_path: Path):
        """首次进入 interview 页(pending_start=True)→ auto-start 触发 → chat_input 渲染。"""
        at = _interview(
            tmp_path / "test.db",
            interview_started=False,
            mock_responses=["第一题:请自我介绍"],
        )
        at.session_state["pending_start"] = True
        at.session_state["jd_content"] = "Python 后端"
        at.run()

        # auto-start 触发后:interview_started=True,chat_history 至少 1 个 assistant
        assert at.session_state["interview_started"] is True
        assert len(at.session_state["chat_history"]) >= 1
        last = at.session_state["chat_history"][-1]
        assert last["role"] == "assistant"
        assert "第一题" in last["content"]


# ============================================================================
# 对话交互
# ============================================================================


class TestChatInteraction:
    def test_user_answer_appends_history_and_triggers_feedback(
        self, tmp_path: Path
    ):
        """提交回答 → chat_history 追加 → turn_feedback 追加 → 追问生成。"""
        at = _interview(
            tmp_path / "test.db",
            chat_history=[{"role": "assistant", "content": "q1"}],
            mock_responses=["q2 追问"],
            mock_feedback=["【分数】8/10\n【建议】不错。"],
        )

        at.chat_input[0].set_value("我的回答是后端")
        at.run()

        # chat_history 末尾应追加 user + assistant
        history = at.session_state["chat_history"]
        assert len(history) == 3
        assert history[-2]["role"] == "user"
        assert history[-2]["content"] == "我的回答是后端"
        assert history[-1]["role"] == "assistant"
        assert "q2" in history[-1]["content"]

        # turn_feedback 追加 1 条
        assert len(at.session_state["turn_feedback"]) == 1
        assert at.session_state["turn_feedback"][0]["score"] == 8

    def test_end_signal_triggers_report_nav(self, tmp_path: Path):
        """输入含 END_SIGNAL → _generate_report + 跳报告页。

        pending_report_nav 会被 rerun 顶部消费 + goto("report") 触发跳转,
        所以断言 current_page 已变为 "report"。
        """
        at = _interview(
            tmp_path / "test.db",
            chat_history=[
                {"role": "assistant", "content": "q1"},
                {"role": "user", "content": "a1"},
            ],
            mock_responses=["## 复盘报告\n1. 沟通:7/10"],
            timeout=120,
        )

        at.chat_input[0].set_value(f"好的,{END_SIGNAL}")
        at.run()

        # 报告已生成 + 已跳转(report_nav 在 consume_nav 中消费)
        assert at.session_state["report_text"], "报告未生成"
        assert at.session_state["current_page"] == "report", (
            f"期望 current_page='report',实际: "
            f"{at.session_state.get('current_page')!r}"
        )

    def test_explicit_end_button_triggers_report(self, tmp_path: Path):
        """点结束按钮 → 报告生成 + 跳转。"""
        at = _interview(
            tmp_path / "test.db",
            chat_history=[
                {"role": "assistant", "content": "q1"},
                {"role": "user", "content": "a1"},
            ],
            mock_responses=["## 复盘报告"],
            timeout=120,
        )
        btn = _button_by_label(at, "结束面试")
        assert btn is not None
        btn.click()
        at.run()

        assert at.session_state["report_text"], "报告未生成"
        assert at.session_state["current_page"] == "report", (
            f"期望 current_page='report',实际: "
            f"{at.session_state.get('current_page')!r}"
        )

    def test_feedback_failure_does_not_break_interview(
        self, tmp_path: Path, monkeypatch
    ):
        """反馈 LLM 抛错时,主对话下一题仍正常生成。"""
        from llm import LLMError

        def selective_chat(messages, *, temperature=0.7, purpose="chat", stream=False):
            if purpose == "feedback":
                raise LLMError("feedback failed")
            # at.session_state 没 .get(),用 in + [] 切片
            mock_q = at.session_state["mock_responses"] if "mock_responses" in at.session_state else None
            if isinstance(mock_q, list) and mock_q:
                return mock_q.pop(0)
            return ""

        monkeypatch.setattr("interview_helpers._do_chat", selective_chat)

        at = _interview(
            tmp_path / "test.db",
            chat_history=[{"role": "assistant", "content": "q1"}],
            mock_responses=["q2 追问"],
            timeout=120,
        )
        at.chat_input[0].set_value("my answer")
        at.run()

        # feedback 失败被吞,score=-1 占位
        assert len(at.session_state["turn_feedback"]) == 1
        assert at.session_state["turn_feedback"][0]["score"] == -1
        # 主对话下一题应出现
        history = at.session_state["chat_history"]
        assert history[-1]["role"] == "assistant"
        assert history[-1]["content"]


# ============================================================================
# 错误反馈渲染
# ============================================================================


class TestFeedbackRendering:
    def test_feedback_card_renders_score_and_advice(self, tmp_path: Path):
        """反馈卡渲染分数 + 建议。"""
        at = _interview(
            tmp_path / "test.db",
            chat_history=[
                {"role": "assistant", "content": "q1"},
                {"role": "user", "content": "a1"},
            ],
            turn_feedback=[{"question": "q1", "score": 7, "advice": "补数据"}],
        )
        md = "\n".join(m.value for m in at.markdown)
        assert "7/10" in md
        assert "补数据" in md

    def test_feedback_card_shows_authenticity_warning(self, tmp_path: Path):
        """turn_authenticity_flags 非空时,反馈卡渲染 ⚠️。"""
        at = _interview(
            tmp_path / "test.db",
            chat_history=[
                {"role": "assistant", "content": "q1"},
                {"role": "user", "content": "a1"},
            ],
            turn_feedback=[{"question": "q1", "score": 5, "advice": "x"}],
            turn_authenticity_flags=[["过于简短"]],
        )
        md = "\n".join(m.value for m in at.markdown)
        assert "⚠️" in md
        assert "过于简短" in md

    def test_feedback_card_omits_warning_when_no_flags(self, tmp_path: Path):
        """turn_authenticity_flags 为空时,无 ⚠️。"""
        at = _interview(
            tmp_path / "test.db",
            chat_history=[
                {"role": "assistant", "content": "q1"},
                {"role": "user", "content": "a1"},
            ],
            turn_feedback=[{"question": "q1", "score": 7, "advice": "ok"}],
            turn_authenticity_flags=[[]],
        )
        md = "\n".join(m.value for m in at.markdown)
        assert "⚠️" not in md


# ============================================================================
# 持久化
# ============================================================================


class TestPersistence:
    def test_report_saved_to_db_with_correct_mode(
        self, tmp_path: Path, monkeypatch
    ):
        """结束面试 → save_session 落盘(mode=interview)。"""
        db = tmp_path / "test.db"
        at = _interview(
            db,
            chat_history=[
                {"role": "assistant", "content": "q1"},
                {"role": "user", "content": "a1"},
            ],
            mock_responses=["## 复盘报告"],
        )
        btn = _button_by_label(at, "结束面试")
        btn.click()
        at.run()

        with sqlite3.connect(str(db)) as conn:
            rows = conn.execute(
                "SELECT mode, level, turn_count FROM interview_sessions"
            ).fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "interview"
        assert rows[0][1] == "社招(中级)"
        assert rows[0][2] == 1

    def test_practice_report_saved_with_mode_practice(self, tmp_path: Path):
        """practice 模式结束 → mode='practice'。"""
        db = tmp_path / "test.db"
        at = _interview(
            db,
            practice_mode=True,
            practice_topic="kafka",
            chat_history=[
                {"role": "assistant", "content": "q1"},
                {"role": "user", "content": "a1"},
            ],
            mock_responses=["## 复盘报告"],
        )
        btn = _button_by_label(at, "退出专项训练")
        btn.click()
        at.run()

        with sqlite3.connect(str(db)) as conn:
            row = conn.execute(
                "SELECT mode FROM interview_sessions"
            ).fetchone()
        assert row[0] == "practice"

    def test_practice_exit_via_text_signal(self, tmp_path: Path):
        """输入含『退出专项训练』→ 报告生成 + 跳转。"""
        db = tmp_path / "test.db"
        at = _interview(
            db,
            practice_mode=True,
            practice_topic="kafka",
            chat_history=[
                {"role": "assistant", "content": "q1"},
                {"role": "user", "content": "a1"},
            ],
            mock_responses=["## 复盘报告"],
            timeout=120,
        )
        at.chat_input[0].set_value("好的,退出专项训练")
        at.run()

        assert at.session_state["report_text"], "报告未生成"
        assert at.session_state["practice_mode"] is False
        assert at.session_state["practice_topic"] == ""

    def test_resume_text_not_persisted(self, tmp_path: Path):
        """简历原文不应落盘(只存 hash)。"""
        db = tmp_path / "test.db"
        at = _interview(
            db,
            chat_history=[
                {"role": "assistant", "content": "q1"},
                {"role": "user", "content": "a1"},
            ],
            mock_responses=["## 复盘报告"],
        )
        at.session_state["resume_content"] = (
            "张三_PII_SECRET_身份证_11010119900101_简历"
        )
        at.run()

        btn = _button_by_label(at, "结束面试")
        btn.click()
        at.run()

        with sqlite3.connect(str(db)) as conn:
            all_text = ""
            for table in ("interview_sessions", "interview_turns", "turn_feedback"):
                rows = conn.execute(f"SELECT * FROM {table}").fetchall()
                for r in rows:
                    all_text += str(r) + "\n"
        assert "张三_PII_SECRET" not in all_text
        assert "11010119900101" not in all_text


# ============================================================================
# 报告生成
# ============================================================================


class TestReportGeneration:
    def test_report_includes_authenticity_section_when_valid(
        self, tmp_path: Path, monkeypatch
    ):
        """完整流程跑下来,auth score=0.7 时报告含第 7 段。"""
        # mock_responses 序列:
        # - q1:用户 a1 后的追问
        # - ## 复盘报告:报告生成
        # - auth JSON:真实性聚合
        responses = [
            "q1",
            "## 复盘报告\n1. 沟通:7/10",
            '{"score": 0.7, "findings": [{"turn": 1, "issue": "模板化", "detail": "泛词无数据"}], "summary": "整体可改进"}',
        ]
        at = _interview(
            tmp_path / "test.db",
            chat_history=[{"role": "assistant", "content": "q0"}],
            mock_responses=responses,
            timeout=120,
        )
        at.session_state["resume_content"] = "张三 5年 Python 后端 订单系统"
        at.chat_input[0].set_value("a1")
        at.run()
        at.chat_input[0].set_value(f"a2,{END_SIGNAL}")
        at.run()

        assert at.session_state["report_text"], "报告未生成"
        assert "真实性" in at.session_state["report_text"]
        assert "70" in at.session_state["report_text"]
        assert "模板化" in at.session_state["report_text"]

    def test_turn_feedback_passed_to_report_prompt(
        self, tmp_path: Path, monkeypatch
    ):
        """结束面试时,turn_feedback 应透传给 build_report_prompt。"""
        captured = {}

        def fake_report_prompt(*args, **kwargs):
            captured["turn_feedback"] = kwargs.get("turn_feedback")
            captured["called"] = True
            return "REPORT_PROMPT_STUB"

        monkeypatch.setattr("prompts.build_report_prompt", fake_report_prompt)

        at = _interview(
            tmp_path / "test.db",
            chat_history=[
                {"role": "assistant", "content": "q1"},
                {"role": "user", "content": "a1"},
                {"role": "assistant", "content": "q2"},
                {"role": "user", "content": "a2"},
            ],
            turn_feedback=[
                {"question": "q1", "score": 8, "advice": "ok1"},
                {"question": "q2", "score": 6, "advice": "ok2"},
            ],
            mock_responses=["## 复盘报告"],
            timeout=120,
        )
        btn = _button_by_label(at, "结束面试")
        btn.click()
        at.run()

        assert captured.get("called") is True
        tf = captured.get("turn_feedback")
        assert tf is not None
        assert len(tf) == 2
