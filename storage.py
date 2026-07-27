"""面试历史持久化层:SQLite 存盘 + 只读加载。

设计原则:
- 零新依赖(SQLite 是 stdlib)
- 所有函数显式接受 db_path(测试友好,生产用 DEFAULT_DB_PATH)
- 单用户工具:所有 session 共用 candidate_id="default",不分简历
- 单事务写 3 表,失败原子回滚
- ON DELETE CASCADE 留接口给后续删除功能
"""
from __future__ import annotations

import hashlib
import json
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

CREATE TABLE IF NOT EXISTS interview_autosave (
    candidate_id    TEXT PRIMARY KEY,
    state_json      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
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
    """建表(幂等,IF NOT EXISTS)。db_path=None 时从 env 读。

    v0.3: 单用户模式下,把历史上 c_* 格式的 candidate_id 收敛到 "default",
    让 alpha 测试期落的数据仍可见(一次性,UPDATE 影响行数 = 0 后幂等)。
    """
    with _connect(db_path) as conn:
        conn.executescript(SCHEMA)
        # 单用户迁移:旧 c_xxx → default
        conn.execute(
            "UPDATE interview_sessions SET candidate_id='default' "
            "WHERE candidate_id LIKE 'c_%'"
        )


def get_candidate_id() -> str:
    """返回当前 candidate_id。单用户工具固定 'default'(不再按简历切分)。

    函数签名保留 `()` 而非常量的原因:未来若引入多用户切换,只改这一个函数。
    """
    return "default"


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
    cid = get_candidate_id()
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
    db_path: Path | None, candidate_id: str, *,
    limit: int = 5,
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


# ============================================================================
# 进行中面试草稿(interview-autosave):刷新后续答
# ============================================================================


def save_autosave(
    db_path: Path | None, candidate_id: str, state: dict
) -> None:
    """写入/覆盖该 candidate 的进行中面试草稿(单行 UPSERT)。"""
    if db_path is None:
        db_path = _default_db_path()
    state_json = json.dumps(state, ensure_ascii=False)
    now = datetime.now(timezone.utc).isoformat()
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO interview_autosave (candidate_id, state_json, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(candidate_id) DO UPDATE SET
                state_json = excluded.state_json,
                updated_at = excluded.updated_at
            """,
            (candidate_id, state_json, now),
        )


def load_autosave(db_path: Path | None, candidate_id: str) -> dict | None:
    """读取该 candidate 的草稿。不存在或 JSON 损坏 → None。"""
    if db_path is None:
        db_path = _default_db_path()
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT state_json FROM interview_autosave WHERE candidate_id = ?",
            (candidate_id,),
        ).fetchone()
    if row is None:
        return None
    try:
        return json.loads(row["state_json"])
    except (ValueError, TypeError):
        return None


def clear_autosave(db_path: Path | None, candidate_id: str) -> None:
    """删除该 candidate 的草稿(幂等,不存在也不报错)。"""
    if db_path is None:
        db_path = _default_db_path()
    with _connect(db_path) as conn:
        conn.execute(
            "DELETE FROM interview_autosave WHERE candidate_id = ?",
            (candidate_id,),
        )


# ============================================================================
# 删除 / 保留清理(v0.3 alpha-kickoff)
# ============================================================================


def delete_session(db_path: Path | None, session_id: str) -> bool:
    """删除单条 session。turns/feedback 通过 ON DELETE CASCADE 级联清。

    Returns:
        True: 删了;False: 不存在。
    """
    if db_path is None:
        db_path = _default_db_path()
    with _connect(db_path) as conn:
        cur = conn.execute(
            "DELETE FROM interview_sessions WHERE id = ?", (session_id,)
        )
    return cur.rowcount > 0


def clear_all_sessions_for_candidate(
    db_path: Path | None, candidate_id: str
) -> int:
    """清空该 candidate 全部 session。Returns 删除条数。"""
    if db_path is None:
        db_path = _default_db_path()
    with _connect(db_path) as conn:
        cur = conn.execute(
            "DELETE FROM interview_sessions WHERE candidate_id = ?",
            (candidate_id,),
        )
    return cur.rowcount


def purge_expired_sessions(
    db_path: Path | None, retention_days: int
) -> int:
    """删除 ended_at 早于 (now - retention_days) 的 session。

    retention_days <= 0 → 不删(返回 0)。
    Returns 删除条数。
    """
    if retention_days <= 0:
        return 0
    if db_path is None:
        db_path = _default_db_path()
    cutoff = datetime.now(timezone.utc).timestamp() - retention_days * 86400
    cutoff_iso = datetime.fromtimestamp(cutoff, tz=timezone.utc).isoformat()
    with _connect(db_path) as conn:
        cur = conn.execute(
            "DELETE FROM interview_sessions WHERE ended_at < ?",
            (cutoff_iso,),
        )
    return cur.rowcount
