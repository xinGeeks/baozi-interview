"""storage.py practice 模式扩展测试。

覆盖:
- 幂等迁移:v0.3 风格 DB(无 mode 列)经 init_db 后新增 mode 列 + 老行 backfill
- save_session 持久化 mode='practice' / mode='interview'
- extract_and_store_for_session 跳过 mode='practice' 的 session(防污染 cache)
- list_sessions 按 mode 过滤(None=全部 / interview=仅正常 / practice=仅练习)
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from storage import (
    extract_and_store_for_session,
    get_session,
    get_topics_for_candidate,
    init_db,
    list_sessions,
    save_session,
    write_topic_facts,
)
from topic_extraction import TopicFact


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def db(tmp_path: Path) -> Path:
    p = tmp_path / "test.db"
    init_db(p)
    return p


def _save_chat(num_user_turns: int = 4) -> tuple[list[dict], list[dict], str]:
    chat: list[dict] = []
    for i in range(num_user_turns):
        chat.append({"role": "assistant", "content": f"q {i}"})
        chat.append({
            "role": "user",
            "content": "redis 缓存 kafka 消息队列 redis 缓存 kafka 消息队列",
        })
    feedback = [
        {"question": f"q{i}", "score": 5, "advice": ""}
        for i in range(num_user_turns)
    ]
    return chat, feedback, "报告"


# ============================================================================
# 1.1 幂等迁移:加 mode 列
# ============================================================================


def test_init_db_adds_mode_column_to_existing_db(tmp_path: Path):
    """v0.3 风格 DB(无 mode 列)→ init_db 后新增 mode 列,默认 'interview'。"""
    db = tmp_path / "legacy.db"
    # 手工建 v0.3 风格 interview_sessions(无 mode 列)+ 一行数据
    with sqlite3.connect(str(db)) as conn:
        conn.executescript("""
            CREATE TABLE interview_sessions (
                id TEXT PRIMARY KEY,
                candidate_id TEXT NOT NULL,
                started_at TEXT NOT NULL,
                ended_at TEXT NOT NULL,
                level TEXT NOT NULL,
                style TEXT NOT NULL,
                jd_summary TEXT NOT NULL,
                jd_hash TEXT NOT NULL,
                score_avg REAL,
                report_text TEXT NOT NULL,
                turn_count INTEGER NOT NULL
            );
            INSERT INTO interview_sessions
              (id, candidate_id, started_at, ended_at, level, style,
               jd_summary, jd_hash, score_avg, report_text, turn_count)
              VALUES ('legacy1', 'default', '2026-01-01T00:00:00Z',
                      '2026-01-01T01:00:00Z', 'P5', '温和', 'jd', 'h',
                      7.0, '报告', 3);
        """)
        conn.commit()

    # init_db 应幂等地加 mode 列(老行 backfill 为 'interview')
    init_db(db)

    with sqlite3.connect(str(db)) as conn:
        # 1. mode 列存在
        cols = {
            row[1]
            for row in conn.execute("PRAGMA table_info('interview_sessions')")
        }
        assert "mode" in cols
        # 2. 老行 backfill 为 'interview'
        mode = conn.execute(
            "SELECT mode FROM interview_sessions WHERE id='legacy1'"
        ).fetchone()[0]
    assert mode == "interview"


# ============================================================================
# 1.2 save_session 持久化 mode
# ============================================================================


def test_save_session_persists_practice_mode(db: Path):
    chat, feedback, report = _save_chat(num_user_turns=3)
    sid = save_session(
        db_path=db,
        level="P5",
        style="温和",
        jd="",
        resume_text="",
        chat_history=chat,
        turn_feedback=feedback,
        report_text=report,
        started_at=datetime.now(timezone.utc),
        mode="practice",
    )
    sess = get_session(db, sid)
    assert sess is not None
    assert sess["mode"] == "practice"


def test_save_session_default_mode_is_interview(db: Path):
    """不传 mode → 默认 'interview'(向后兼容)。"""
    chat, feedback, report = _save_chat(num_user_turns=3)
    sid = save_session(
        db_path=db,
        level="P5",
        style="温和",
        jd="",
        resume_text="",
        chat_history=chat,
        turn_feedback=feedback,
        report_text=report,
        started_at=datetime.now(timezone.utc),
    )
    sess = get_session(db, sid)
    assert sess is not None
    assert sess["mode"] == "interview"


# ============================================================================
# 1.3 extract_and_store_for_session 跳过 practice session
# ============================================================================


def test_extract_skips_practice_sessions(db: Path):
    """save 一个 practice session 并直接 write_topic_facts 模拟有事实,
    但 extract_and_store_for_session 内部应 short-circuit 返回 0(不写 cache)。
    """
    chat, feedback, report = _save_chat(num_user_turns=4)
    sid = save_session(
        db_path=db,
        level="P5",
        style="温和",
        jd="",
        resume_text="",
        chat_history=chat,
        turn_feedback=feedback,
        report_text=report,
        started_at=datetime.now(timezone.utc),
        mode="practice",
    )
    # 预写 topic_facts(模拟已抽取过)
    write_topic_facts(
        db, sid,
        [TopicFact(topic="redis", score=0.1, source_turn=1)],
    )
    # extract 仍应跳过(不写 cache)
    n = extract_and_store_for_session(db, sid, "default")
    assert n == 0
    # 候选 cache 应为空
    assert get_topics_for_candidate(db, "default") == []


def test_extract_runs_for_interview_sessions(db: Path):
    """对照:interview 模式仍正常写 cache。"""
    chat, feedback, report = _save_chat(num_user_turns=4)
    sid = save_session(
        db_path=db,
        level="P5",
        style="温和",
        jd="",
        resume_text="",
        chat_history=chat,
        turn_feedback=feedback,
        report_text=report,
        started_at=datetime.now(timezone.utc),
        mode="interview",
    )
    n = extract_and_store_for_session(db, sid, "default")
    assert n >= 1
    assert len(get_topics_for_candidate(db, "default")) >= 1


# ============================================================================
# 1.4 list_sessions 按 mode 过滤
# ============================================================================


def test_list_sessions_filter_by_practice(db: Path):
    """存 1 interview + 1 practice → list_sessions(mode='practice') 只返回 practice。"""
    chat, feedback, report = _save_chat(num_user_turns=3)
    save_session(
        db_path=db, level="P5", style="温和", jd="", resume_text="",
        chat_history=chat, turn_feedback=feedback, report_text=report,
        started_at=datetime.now(timezone.utc), mode="interview",
    )
    save_session(
        db_path=db, level="P5", style="温和", jd="", resume_text="",
        chat_history=chat, turn_feedback=feedback, report_text=report,
        started_at=datetime.now(timezone.utc), mode="practice",
    )
    practice = list_sessions(db, "default", mode="practice")
    interview = list_sessions(db, "default", mode="interview")
    all_sess = list_sessions(db, "default")  # 不传 mode → 全部

    assert len(practice) == 1
    assert practice[0]["mode"] == "practice"
    assert len(interview) == 1
    assert interview[0]["mode"] == "interview"
    assert len(all_sess) == 2


def test_list_sessions_no_filter_returns_all_modes(db: Path):
    """不传 mode → 返回 interview + practice 全集(向后兼容)。"""
    chat, feedback, report = _save_chat(num_user_turns=3)
    save_session(
        db_path=db, level="P5", style="温和", jd="", resume_text="",
        chat_history=chat, turn_feedback=feedback, report_text=report,
        started_at=datetime.now(timezone.utc), mode="interview",
    )
    save_session(
        db_path=db, level="P5", style="温和", jd="", resume_text="",
        chat_history=chat, turn_feedback=feedback, report_text=report,
        started_at=datetime.now(timezone.utc), mode="practice",
    )
    all_sess = list_sessions(db, "default")
    assert len(all_sess) == 2
    assert {s["mode"] for s in all_sess} == {"interview", "practice"}
