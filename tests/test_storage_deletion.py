"""delete_session / clear_all / purge_expired 单元测试。

外加 CASCADE 验证(turns/feedback 跟着 session 一起被清)。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from storage import (
    clear_all_sessions_for_candidate,
    delete_session,
    get_candidate_id,
    get_session,
    init_db,
    purge_expired_sessions,
    save_session,
)


def _make_session(
    db_path: Path,
    resume_text: str = "测试候选人简历内容",
    ended_at: datetime | None = None,
    level: str = "校招",
    style: str = "温和引导",
) -> str:
    """辅助:落盘一条 session(可指定 ended_at 和简历)。

    单用户模式:resume_text 参数保留只为兼容旧调用,不影响 candidate_id。
    """
    started = (ended_at or datetime.now(timezone.utc)) - timedelta(minutes=10)
    sid = save_session(
        db_path=db_path,
        level=level,
        style=style,
        jd="招后端 Python",
        resume_text=resume_text,
        chat_history=[
            {"role": "assistant", "content": "q1"},
            {"role": "user", "content": "a1"},
        ],
        turn_feedback=[
            {"question": "q1", "score": 7, "advice": "good"},
        ],
        report_text="# 报告",
        started_at=started,
        ended_at=ended_at or datetime.now(timezone.utc),
    )
    return sid


class TestDeleteSession:
    def test_delete_existing_returns_true(self, tmp_path: Path):
        db = tmp_path / "test.db"
        init_db(db)
        sid = _make_session(db, "候选人 A 简历")
        assert delete_session(db, sid) is True
        assert get_session(db, sid) is None

    def test_delete_nonexistent_returns_false(self, tmp_path: Path):
        db = tmp_path / "test.db"
        init_db(db)
        assert delete_session(db, "nonexistent") is False

    def test_cascade_deletes_turns_and_feedback(self, tmp_path: Path):
        """ON DELETE CASCADE → 删 session 自动清 turns/feedback。"""
        import sqlite3
        db = tmp_path / "test.db"
        init_db(db)
        sid = _make_session(db, "候选人 B 简历")
        # 先确认 turns/feedback 有数据
        with sqlite3.connect(str(db)) as conn:
            t = conn.execute(
                "SELECT COUNT(*) FROM interview_turns WHERE session_id=?", (sid,)
            ).fetchone()[0]
            f = conn.execute(
                "SELECT COUNT(*) FROM turn_feedback WHERE session_id=?", (sid,)
            ).fetchone()[0]
        assert t == 2 and f == 1
        # 删 session
        delete_session(db, sid)
        # turns/feedback 应级联清
        with sqlite3.connect(str(db)) as conn:
            t = conn.execute(
                "SELECT COUNT(*) FROM interview_turns WHERE session_id=?", (sid,)
            ).fetchone()[0]
            f = conn.execute(
                "SELECT COUNT(*) FROM turn_feedback WHERE session_id=?", (sid,)
            ).fetchone()[0]
        assert t == 0 and f == 0


class TestClearAllForCandidate:
    def test_clear_clears_all_in_single_user_mode(self, tmp_path: Path):
        """单用户模式:clear_all 清掉所有 default bucket 下的 session。"""
        from storage import list_sessions
        db = tmp_path / "test.db"
        init_db(db)
        _make_session(db, "候选人 A 简历")
        _make_session(db, "候选人 A 简历")
        _make_session(db, "候选人 B 简历")
        n = clear_all_sessions_for_candidate(db, get_candidate_id())
        assert n == 3
        assert len(list_sessions(db, get_candidate_id(), limit=10)) == 0

    def test_clear_empty_candidate_returns_zero(self, tmp_path: Path):
        db = tmp_path / "test.db"
        init_db(db)
        assert clear_all_sessions_for_candidate(db, "default") == 0


class TestPurgeExpired:
    def test_purge_removes_old_sessions(self, tmp_path: Path):
        from storage import list_sessions
        db = tmp_path / "test.db"
        init_db(db)
        # 100 天前
        old = datetime.now(timezone.utc) - timedelta(days=100)
        _make_session(db, "候选人 A 简历", ended_at=old)
        # 今天
        _make_session(db, "候选人 A 简历", ended_at=datetime.now(timezone.utc))
        # 30 天阈值
        n = purge_expired_sessions(db, retention_days=30)
        assert n == 1
        # 今天的还在
        assert len(list_sessions(db, get_candidate_id(), limit=10)) == 1

    def test_purge_zero_days_disables(self, tmp_path: Path):
        """retention_days=0 → 不删(返回 0)。"""
        from storage import list_sessions
        db = tmp_path / "test.db"
        init_db(db)
        old = datetime.now(timezone.utc) - timedelta(days=1000)
        _make_session(db, "候选人 A 简历", ended_at=old)
        n = purge_expired_sessions(db, retention_days=0)
        assert n == 0
        assert len(list_sessions(db, get_candidate_id(), limit=10)) == 1

    def test_purge_negative_days_disables(self, tmp_path: Path):
        db = tmp_path / "test.db"
        init_db(db)
        _make_session(db, "候选人 A 简历")
        n = purge_expired_sessions(db, retention_days=-1)
        assert n == 0

    def test_purge_cascades_to_turns(self, tmp_path: Path):
        import sqlite3
        db = tmp_path / "test.db"
        init_db(db)
        old = datetime.now(timezone.utc) - timedelta(days=100)
        sid = _make_session(db, "候选人 A 简历", ended_at=old)
        purge_expired_sessions(db, retention_days=30)
        with sqlite3.connect(str(db)) as conn:
            t = conn.execute(
                "SELECT COUNT(*) FROM interview_turns WHERE session_id=?", (sid,)
            ).fetchone()[0]
        assert t == 0
