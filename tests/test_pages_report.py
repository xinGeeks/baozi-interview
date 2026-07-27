"""pages/report.py 集成测试。"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from streamlit.testing.v1 import AppTest

from storage import init_db, save_session


def _report_page(
    db_path: Path,
    *,
    report_text: str = "",
    viewing_history: bool = False,
    loaded_session_id: str = "",
) -> AppTest:
    os.environ["STORAGE_DB_PATH"] = str(db_path)
    init_db(db_path)
    at = AppTest.from_file("app.py", default_timeout=30)
    at.run()
    at.switch_page("pages/report.py")
    at.session_state["report_text"] = report_text
    at.session_state["viewing_history"] = viewing_history
    at.session_state["loaded_session_id"] = loaded_session_id
    at.run()
    return at


def _save_history(db_path: Path) -> str:
    init_db(db_path)
    return save_session(
        db_path=db_path,
        level="社招(中级)",
        style="温和引导",
        jd="Python 后端",
        resume_text="",
        chat_history=[
            {"role": "assistant", "content": "请介绍项目"},
            {"role": "user", "content": "我负责订单系统"},
        ],
        turn_feedback=[{"question": "请介绍项目", "score": 8, "advice": "补充数据"}],
        report_text="历史报告正文",
        started_at=datetime(2026, 7, 20, tzinfo=timezone.utc),
        ended_at=datetime(2026, 7, 20, 12, tzinfo=timezone.utc),
    )


def _button_by_label(at: AppTest, needle: str):
    return next((b for b in at.button if needle in str(b.label or "")), None)


def test_current_report_renders_download_and_explicit_navigation(tmp_path: Path):
    at = _report_page(tmp_path / "report.db", report_text="# 本场报告")

    assert any("本场报告" in str(m.value) for m in at.markdown)
    assert len(at.download_button) == 1
    assert _button_by_label(at, "下一场") is not None
    assert _button_by_label(at, "查看训练图谱") is not None
    assert at.session_state["current_page"] == "report"


def test_report_does_not_auto_advance_without_click(tmp_path: Path):
    at = _report_page(tmp_path / "report.db", report_text="# 本场报告")
    assert at.session_state["current_page"] == "report"
    assert at.session_state["pending_goto"] == ""


def test_history_segment_lists_saved_session(tmp_path: Path):
    db = tmp_path / "report.db"
    sid = _save_history(db)
    at = _report_page(db)

    segment = at.segmented_control[0]
    segment.set_value("历史报告")
    at.run()

    labels = [str(b.label or "") for b in at.button]
    assert any("2026-07-20" in label and "1 轮" in label for label in labels)
    assert at.session_state["viewing_history"] is False


def test_history_session_renders_read_only_view(tmp_path: Path):
    db = tmp_path / "report.db"
    sid = _save_history(db)
    at = _report_page(
        db,
        viewing_history=True,
        loaded_session_id=sid,
    )

    text = "\n".join(str(m.value) for m in at.markdown)
    assert "请介绍项目" in text
    assert "历史报告正文" in text
    assert len(at.download_button) == 1


def test_next_session_requests_config_navigation(tmp_path: Path):
    at = _report_page(tmp_path / "report.db", report_text="# 本场报告")
    button = _button_by_label(at, "下一场")
    assert button is not None
    button.click()
    at.run()

    assert at.session_state["current_page"] == "config"
    assert at.session_state["interview_started"] is False
    assert at.session_state["report_text"] == ""


def test_topics_button_requests_topics_navigation(tmp_path: Path):
    at = _report_page(tmp_path / "report.db", report_text="# 本场报告")
    button = _button_by_label(at, "查看训练图谱")
    assert button is not None
    button.click()
    at.run()

    assert at.session_state["current_page"] == "topics"
