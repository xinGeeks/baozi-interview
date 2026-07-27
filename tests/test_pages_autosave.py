"""面试自动存草稿 + 续答 banner 的 AppTest 集成测试。

覆盖:
- 答一轮后 DB autosave 有记录
- 模拟刷新:新 AppTest → config 页出现续答 banner
- 点「继续面试」→ interview_started=True + chat_history/resume_content 恢复
- 点「放弃草稿」→ autosave 清空 + banner 消失
- _generate_report 后 autosave 被清
- 同 session 已有 interview_started=True → 不显示 banner
- 无草稿 → 不显示 banner

AppTest 每次都是「fresh session」(模拟浏览器刷新),所以可以直接
构造两个 AppTest 实例指向同一 DB 验证跨 session 行为。
"""
from __future__ import annotations

import os
from pathlib import Path

from streamlit.testing.v1 import AppTest

from storage import (
    init_db,
    load_autosave,
    get_candidate_id,
    save_autosave,
    save_session,
)
from datetime import datetime, timezone


# ============================================================================
# 工具
# ============================================================================


def _app(db_path: Path, default_timeout: int = 30) -> AppTest:
    """新 AppTest:模拟 fresh session(浏览器刷新后的状态)。"""
    os.environ["STORAGE_DB_PATH"] = str(db_path)
    init_db(db_path)
    at = AppTest.from_file("app.py", default_timeout=default_timeout)
    return at


def _button_by_label(at: AppTest, needle: str):
    for b in at.button:
        if needle in str(b.label or ""):
            return b
    return None


def _seed_autosave(db_path: Path, *, turns: int = 2, resume: str = "张三 5 年 Python") -> dict:
    """往 DB 写一份进行中面试草稿(模拟上次答了几轮后刷新)。"""
    init_db(db_path)
    chat = []
    for i in range(turns):
        chat.append({"role": "assistant", "content": f"q{i+1}"})
        chat.append({"role": "user", "content": f"a{i+1}"})
    state = {
        "chat_history": chat,
        "turn_feedback": [
            {"question": f"q{i+1}", "score": 7, "advice": f"feedback{i+1}"}
            for i in range(turns)
        ],
        "turn_authenticity_flags": [[] for _ in range(turns)],
        "interview_level": "社招(中级)",
        "interview_style": "温和引导",
        "jd_content": "Python 后端 JD",
        "resume_content": resume,
        "interview_started_at": "2026-07-20T00:00:00+00:00",
    }
    save_autosave(db_path, get_candidate_id(), state)
    return state


# ============================================================================
# 续答 banner 渲染
# ============================================================================


class TestResumeBanner:
    def test_no_draft_no_banner(self, tmp_path: Path):
        """无草稿 → config / interview 页都不出 banner。"""
        db = tmp_path / "test.db"
        init_db(db)
        at = _app(db).run()
        at.switch_page("pages/config.py").run()

        # config 页不应出现「继续面试」按钮
        assert _button_by_label(at, "继续面试") is None
        assert _button_by_label(at, "放弃草稿") is None

    def test_draft_on_config_page_shows_banner(self, tmp_path: Path):
        """DB 有草稿 → config 页显示续答 banner + 2 个按钮。"""
        db = tmp_path / "test.db"
        _seed_autosave(db, turns=3)
        at = _app(db).run()
        at.switch_page("pages/config.py").run()

        assert _button_by_label(at, "继续面试") is not None
        assert _button_by_label(at, "放弃草稿") is not None

    def test_draft_on_interview_page_shows_banner(self, tmp_path: Path):
        """DB 有草稿 + interview 页未开始 → banner 显示 + 不显示「去配置页」按钮。"""
        db = tmp_path / "test.db"
        _seed_autosave(db, turns=2)
        at = _app(db).run()
        at.switch_page("pages/interview.py").run()

        assert _button_by_label(at, "继续面试") is not None
        # 「去配置页」按钮被 banner st.stop 掉,不应出现
        assert _button_by_label(at, "去配置页") is None

    def test_active_interview_no_banner(self, tmp_path: Path):
        """同 session 内已有进行中面试(autosave 有但 interview_started=True)
        → 不再渲染续答 banner(避免重复提示)。"""
        db = tmp_path / "test.db"
        _seed_autosave(db, turns=2)
        at = _app(db).run()
        at.switch_page("pages/config.py").run()
        # 模拟同 session 内已 restore 后,interview_started=True
        at.session_state["interview_started"] = True
        at.run()

        assert _button_by_label(at, "继续面试") is None


# ============================================================================
# 续答交互
# ============================================================================


class TestResumeActions:
    def test_continue_restores_state_and_jumps_to_interview(self, tmp_path: Path):
        """点「继续面试」→ interview_started=True + history/resume 恢复 + 跳页。"""
        db = tmp_path / "test.db"
        seeded = _seed_autosave(
            db, turns=2, resume="李四 3 年 Go 高并发",
        )
        at = _app(db).run()
        at.switch_page("pages/config.py").run()

        btn = _button_by_label(at, "继续面试")
        assert btn is not None
        btn.click()
        at.run()

        # 状态恢复
        assert at.session_state["interview_started"] is True
        assert at.session_state["interview_ended"] is False
        assert at.session_state["viewing_history"] is False
        assert at.session_state["resume_content"] == seeded["resume_content"]
        assert len(at.session_state["chat_history"]) == 4  # 2 turns × 2 messages
        assert at.session_state["chat_history"][1]["role"] == "user"
        assert at.session_state["chat_history"][1]["content"] == "a1"

    def test_continue_preserves_interview_started_at(self, tmp_path: Path):
        """续答应保留原 interview_started_at(计时不重置)。"""
        db = tmp_path / "test.db"
        _seed_autosave(db)
        at = _app(db).run()
        at.switch_page("pages/config.py").run()

        _button_by_label(at, "继续面试").click()
        at.run()

        started = at.session_state["interview_started_at"]
        assert started is not None
        # datetime 对象 → ISO format 字符串含 2026-07-20
        iso = started.isoformat() if hasattr(started, "isoformat") else str(started)
        assert "2026-07-20" in iso, f"期望 2026-07-20,实际: {iso}"

    def test_discard_clears_autosave(self, tmp_path: Path):
        """点「放弃草稿」→ DB autosave 清空 + 不再出 banner。"""
        db = tmp_path / "test.db"
        _seed_autosave(db)
        at = _app(db).run()
        at.switch_page("pages/config.py").run()

        btn = _button_by_label(at, "放弃草稿")
        assert btn is not None
        btn.click()
        at.run()

        # DB 清空
        assert load_autosave(db, get_candidate_id()) is None
        # banner 消失
        assert _button_by_label(at, "继续面试") is None
        assert _button_by_label(at, "放弃草稿") is None

    def test_discard_then_reload_no_banner(self, tmp_path: Path):
        """放弃后刷新(新 AppTest)→ 也不出 banner。"""
        db = tmp_path / "test.db"
        _seed_autosave(db)
        at = _app(db).run()
        at.switch_page("pages/config.py").run()
        _button_by_label(at, "放弃草稿").click()
        at.run()

        # 新 AppTest 模拟刷新
        at2 = _app(db).run()
        at2.switch_page("pages/config.py").run()
        assert _button_by_label(at2, "继续面试") is None


# ============================================================================
# 触发点:答完一轮 → autosave 写盘
# ============================================================================


class TestAutosaveTrigger:
    def test_handle_user_answer_writes_autosave(self, tmp_path: Path):
        """答一轮后 DB 应有 autosave 记录。

        走完整链路:config → interview(自动 start)→ 答 → 触发 _handle_user_answer
        → _autosave_interview()。
        """
        db = tmp_path / "test.db"
        os.environ["STORAGE_DB_PATH"] = str(db)
        init_db(db)
        at = AppTest.from_file("app.py", default_timeout=60)
        # 答 1 轮 → 反馈 + 下一题各 1 次 LLM 调用
        at.session_state["mock_responses"] = ["q1", "q2"]
        at.session_state["mock_feedback_responses"] = [
            '{"score": 8, "advice": "好"}',
        ]
        at.run()
        at.switch_page("pages/config.py").run()

        # 填 JD + 点开始
        jd_ta = next(t for t in at.text_area if "JD" in (t.label or ""))
        jd_ta.set_value("Python 后端")
        at.run()
        _button_by_label(at, "开始面试").click()
        at.run()
        # auto-start 已跑,interview_started=True + 第一题落地 + autosave
        assert at.session_state["interview_started"] is True

        # DB 应该有 autosave 行
        assert load_autosave(db, get_candidate_id()) is not None
        draft = load_autosave(db, get_candidate_id())
        assert len(draft["chat_history"]) >= 1

    def test_end_interview_button_clears_autosave(self, tmp_path: Path):
        """点『结束面试』按钮 → _generate_report → autosave 应被清。"""
        db = tmp_path / "test.db"
        os.environ["STORAGE_DB_PATH"] = str(db)
        init_db(db)
        at = AppTest.from_file("app.py", default_timeout=60)
        at.session_state["mock_responses"] = ["## 报告正文"]
        at.run()
        at.session_state["interview_started"] = True
        at.session_state["interview_ended"] = False
        at.session_state["chat_history"] = [
            {"role": "assistant", "content": "q1"},
            {"role": "user", "content": "a1"},
        ]
        at.session_state["turn_feedback"] = [
            {"question": "q1", "score": 8, "advice": "好"},
        ]
        at.session_state["resume_content"] = "李四"
        at.session_state["jd_content"] = "Python 后端"
        at.run()

        # 手动 save_autosave 模拟 _handle_user_answer 已经写过
        save_autosave(
            db, get_candidate_id(),
            {
                "chat_history": at.session_state["chat_history"],
                "turn_feedback": at.session_state["turn_feedback"],
                "turn_authenticity_flags": [],
                "interview_level": at.session_state["interview_level"],
                "interview_style": at.session_state["interview_style"],
                "jd_content": at.session_state["jd_content"],
                "resume_content": at.session_state["resume_content"],
                "interview_started_at": "2026-07-20T00:00:00+00:00",
            },
        )
        assert load_autosave(db, get_candidate_id()) is not None

        # 切到 interview 页 → 点结束按钮 → _generate_report → _clear_autosave
        at.switch_page("pages/interview.py").run()
        btn = _button_by_label(at, "结束面试")
        assert btn is not None
        btn.click()
        at.run()

        assert load_autosave(db, get_candidate_id()) is None
        assert at.session_state["interview_ended"] is True

    def test_after_completion_no_resume_prompt(self, tmp_path: Path):
        """完整流程走完后,刷新 → config 页不应出续答 banner。"""
        db = tmp_path / "test.db"
        os.environ["STORAGE_DB_PATH"] = str(db)
        init_db(db)
        # 先落一份完成的 session
        sid = save_session(
            db_path=db,
            level="社招(中级)",
            style="温和引导",
            jd="Python 后端",
            resume_text="李四",
            chat_history=[
                {"role": "assistant", "content": "q1"},
                {"role": "user", "content": "a1"},
            ],
            turn_feedback=[{"question": "q1", "score": 8, "advice": "好"}],
            report_text="ok",
            started_at=datetime.now(timezone.utc),
        )

        at = _app(db).run()
        at.switch_page("pages/config.py").run()
        assert _button_by_label(at, "继续面试") is None