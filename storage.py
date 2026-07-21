"""面试历史持久化层:SQLite 存盘 + 只读加载。

设计原则:
- 零新依赖(SQLite 是 stdlib)
- 所有函数显式接受 db_path(测试友好,生产用 DEFAULT_DB_PATH)
- 不存简历原文(PII 安全),只用 MD5 做 candidate_id
- 单事务写 3 表,失败原子回滚
- ON DELETE CASCADE 留接口给后续删除功能
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path


def _default_db_path() -> Path:
    """每次调用时读 STORAGE_DB_PATH(测试隔离用,AppTest 子进程也能用)。"""
    return Path(os.environ.get("STORAGE_DB_PATH", "data/interviews.db"))


# 向后兼容:导出 DEFAULT_DB_PATH(惰性求值,test 用 monkeypatch.setenv 覆盖)
DEFAULT_DB_PATH = _default_db_path()


SCHEMA = """
CREATE TABLE IF NOT EXISTS interview_sessions (
    id              TEXT PRIMARY KEY,
    candidate_id    TEXT NOT NULL,
    started_at      TEXT NOT NULL,
    ended_at        TEXT NOT NULL,
    level           TEXT NOT NULL,
    style           TEXT NOT NULL,
    jd_summary      TEXT NOT NULL,
    jd_hash         TEXT NOT NULL,
    score_avg       REAL,
    report_text     TEXT NOT NULL,
    turn_count      INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sessions_candidate
    ON interview_sessions(candidate_id, ended_at DESC);

CREATE TABLE IF NOT EXISTS interview_turns (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT NOT NULL,
    turn_idx        INTEGER NOT NULL,
    role            TEXT NOT NULL,
    content         TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES interview_sessions(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_turns_session
    ON interview_turns(session_id, turn_idx);

CREATE TABLE IF NOT EXISTS turn_feedback (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT NOT NULL,
    turn_idx        INTEGER NOT NULL,
    question        TEXT NOT NULL,
    score           INTEGER NOT NULL,
    advice          TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES interview_sessions(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_feedback_session
    ON turn_feedback(session_id, turn_idx);
"""


def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    if db_path is None:
        db_path = _default_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: Path | None = None) -> None:
    """建表(幂等,IF NOT EXISTS)。db_path=None 时从 env 读。"""
    with _connect(db_path) as conn:
        conn.executescript(SCHEMA)


def candidate_id_from_resume(resume_text: str) -> str:
    """简历为空 → 'default';否则 'c_' + MD5 头 16 字符。"""
    if not resume_text or not resume_text.strip():
        return "default"
    return "c_" + hashlib.md5(resume_text.encode("utf-8")).hexdigest()[:16]


def save_session(
    *,
    db_path: Path | None = None,
    level: str,
    style: str,
    jd: str,
    resume_text: str,
    chat_history: list[dict],
    turn_feedback: list[dict],
    report_text: str,
    started_at: datetime,
    ended_at: datetime | None = None,
) -> str:
    """落盘一场完整面试,返回 session_id。单事务 3 表。"""
    if db_path is None:
        db_path = _default_db_path()
    ended_at = ended_at or datetime.now(timezone.utc)
    sid = uuid.uuid4().hex[:12]
    cid = candidate_id_from_resume(resume_text)
    jd_hash = hashlib.md5(jd.encode("utf-8")).hexdigest()[:16]
    jd_summary = (
        (jd.strip()[:200] + "…") if len(jd.strip()) > 200 else jd.strip()
    )
    user_turns = [m for m in chat_history if m["role"] == "user"]
    valid_scores = [
        f["score"] for f in turn_feedback if f.get("score", -1) >= 0
    ]
    score_avg = (
        sum(valid_scores) / len(valid_scores) if valid_scores else None
    )

    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO interview_sessions
              (id, candidate_id, started_at, ended_at, level, style,
               jd_summary, jd_hash, score_avg, report_text, turn_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                sid, cid, started_at.isoformat(), ended_at.isoformat(),
                level, style, jd_summary, jd_hash, score_avg, report_text,
                len(user_turns),
            ),
        )
        conn.executemany(
            """
            INSERT INTO interview_turns (session_id, turn_idx, role, content)
            VALUES (?, ?, ?, ?)
            """,
            [
                (sid, i, m["role"], m["content"])
                for i, m in enumerate(chat_history)
            ],
        )
        conn.executemany(
            """
            INSERT INTO turn_feedback
              (session_id, turn_idx, question, score, advice)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (
                    sid, i,
                    f.get("question", ""),
                    f.get("score", -1),
                    f.get("advice", ""),
                )
                for i, f in enumerate(turn_feedback)
            ],
        )
    return sid


def list_sessions(
    db_path: Path | None, candidate_id: str, *, limit: int = 5
) -> list[dict]:
    """返回该 candidate 最近 N 场(按 ended_at DESC)。"""
    if db_path is None:
        db_path = _default_db_path()
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT id, started_at, ended_at, level, style,
                   jd_summary, score_avg, turn_count
            FROM interview_sessions
            WHERE candidate_id = ?
            ORDER BY ended_at DESC
            LIMIT ?
            """,
            (candidate_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def get_session(db_path: Path | None, session_id: str) -> dict | None:
    """返回完整 session(含 turns / feedback)。不存在 → None。"""
    if db_path is None:
        db_path = _default_db_path()
    with _connect(db_path) as conn:
        sess = conn.execute(
            "SELECT * FROM interview_sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        if sess is None:
            return None
        result = dict(sess)
        result["turns"] = [
            dict(r)
            for r in conn.execute(
                """
                SELECT role, content FROM interview_turns
                WHERE session_id = ? ORDER BY turn_idx
                """,
                (session_id,),
            ).fetchall()
        ]
        result["feedback"] = [
            dict(r)
            for r in conn.execute(
                """
                SELECT question, score, advice FROM turn_feedback
                WHERE session_id = ? ORDER BY turn_idx
                """,
                (session_id,),
            ).fetchall()
        ]
        return result