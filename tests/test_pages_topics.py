"""pages/topics.py 集成测试。"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from streamlit.testing.v1 import AppTest

from storage import init_db, save_session, write_candidate_topic_cache
from topic_extraction import TopicFact


def _topics_page(db_path: Path, *, mock_responses: list[str] | None = None) -> AppTest:
    os.environ["STORAGE_DB_PATH"] = str(db_path)
    init_db(db_path)
    at = AppTest.from_file("app.py", default_timeout=60)
    at.run()
    at.switch_page("pages/topics.py")
    if mock_responses is not None:
        at.session_state["mock_responses"] = list(mock_responses)
    at.run()
    return at


def _seed_topics(db_path: Path) -> None:
    init_db(db_path)
    write_candidate_topic_cache(
        db_path,
        "default",
        [
            TopicFact(topic="kafka", score=0.8, source_turn=0),
            TopicFact(topic="redis", score=0.4, source_turn=1),
        ],
    )


def _save_history(db_path: Path) -> str:
    init_db(db_path)
    return save_session(
        db_path=db_path,
        level="社招(中级)",
        style="温和引导",
        jd="后端",
        resume_text="",
        chat_history=[
            {"role": "assistant", "content": "问题"},
            {"role": "user", "content": "回答"},
        ],
        turn_feedback=[],
        report_text="报告",
        started_at=datetime(2026, 7, 19, tzinfo=timezone.utc),
        ended_at=datetime(2026, 7, 19, 12, tzinfo=timezone.utc),
    )


def _button_by_label(at: AppTest, needle: str):
    return next((b for b in at.button if needle in str(b.label or "")), None)


def test_topics_page_renders_two_core_expanders_and_empty_states(tmp_path: Path):
    at = _topics_page(tmp_path / "topics.db")
    labels = [str(e.label or "") for e in at.expander]

    assert any("跨会话训练图谱" in label for label in labels)
    assert any("弱 topic 专项练习" in label for label in labels)
    captions = "\n".join(str(c.value) for c in at.caption)
    assert "暂无跨 session 数据" in captions
    assert "暂无候选主题" in captions


def test_populated_topics_render_cloud_chart_and_candidates(tmp_path: Path):
    db = tmp_path / "topics.db"
    _seed_topics(db)
    at = _topics_page(db)

    markdown = "\n".join(str(m.value) for m in at.markdown)
    assert "kafka" in markdown
    assert "训练主题云" in markdown
    assert len(at.button) >= 2
    assert _button_by_label(at, "📍 kafka") is not None


def test_topic_candidate_enters_practice_interview(tmp_path: Path):
    db = tmp_path / "topics.db"
    _seed_topics(db)
    at = _topics_page(db, mock_responses=["专项第一题"])

    button = _button_by_label(at, "📍 kafka")
    assert button is not None
    button.click()
    at.run()

    assert at.session_state["current_page"] == "interview"
    assert at.session_state["practice_mode"] is True
    assert at.session_state["practice_topic"] == "kafka"
    assert at.session_state["interview_started"] is True
    assert len(at.chat_input) == 1


def test_old_sessions_are_backfilled_when_topics_page_opens(tmp_path: Path):
    db = tmp_path / "backfill.db"
    init_db(db)
    save_session(
        db_path=db,
        level="社招(中级)",
        style="温和引导",
        jd="后端",
        resume_text="",
        chat_history=[
            {"role": "assistant", "content": "问题"},
            {
                "role": "user",
                "content": "redis 缓存 kafka 消息队列 redis 缓存 kafka 消息队列",
            },
            {"role": "assistant", "content": "追问"},
            {
                "role": "user",
                "content": "redis 缓存 kafka 消息队列 redis 缓存 kafka 消息队列",
            },
            {"role": "assistant", "content": "追问"},
            {
                "role": "user",
                "content": "redis 缓存 kafka 消息队列 redis 缓存 kafka 消息队列",
            },
        ],
        turn_feedback=[],
        report_text="报告",
        started_at=datetime(2026, 7, 19, tzinfo=timezone.utc),
        ended_at=datetime(2026, 7, 19, 12, tzinfo=timezone.utc),
    )

    at = _topics_page(db)
    markdown = "\n".join(str(m.value) for m in at.markdown)

    assert "训练主题云" in markdown
    assert _button_by_label(at, "📍 redis") is not None


def test_topics_history_button_requests_report_history_view(tmp_path: Path):
    db = tmp_path / "topics.db"
    sid = _save_history(db)
    at = _topics_page(db)

    button = _button_by_label(at, "2026-07-19")
    assert button is not None
    button.click()
    at.run()

    assert at.session_state["current_page"] == "report"
    assert at.session_state["loaded_session_id"] == sid
    assert at.session_state["viewing_history"] is True
