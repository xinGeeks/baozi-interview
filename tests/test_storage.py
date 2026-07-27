"""storage.py 单元测试。

所有测试用 tmp_path 注入独立 DB,不污染生产 data/interviews.db。
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from storage import (
    DEFAULT_DB_PATH,
    get_candidate_id,
    get_session,
    init_db,
    list_sessions,
    save_session,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def db(tmp_path: Path) -> Path:
    """每个测试用 tmp_path 内的 test.db。"""
    p = tmp_path / "test.db"
    init_db(p)
    return p


def _sample_history() -> tuple[list[dict], list[dict], str]:
    """一组典型的 (chat_history, turn_feedback, report_text)。"""
    chat = [
        {"role": "assistant", "content": "请介绍一下你自己"},
        {"role": "user", "content": "我做 Python 后端 5 年"},
        {"role": "assistant", "content": "讲讲最有挑战的项目"},
        {"role": "user", "content": "电商订单系统,峰值 QPS 5000"},
    ]
    feedback = [
        {"question": "请介绍一下你自己", "score": 7, "advice": "缺数据"},
        {"question": "讲讲最有挑战的项目", "score": 5, "advice": "模糊"},
    ]
    report = "## 复盘报告\n1. 岗位匹配度:7/10 ..."
    return chat, feedback, report


# ============================================================================
# init_db
# ============================================================================

def test_init_db_creates_tables(db: Path):
    with sqlite3.connect(str(db)) as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
    table_names = {r[0] for r in rows}
    assert "interview_sessions" in table_names
    assert "interview_turns" in table_names
    assert "turn_feedback" in table_names


def test_init_db_is_idempotent(tmp_path: Path):
    p = tmp_path / "test.db"
    init_db(p)
    init_db(p)  # 第二次不应抛错
    assert p.exists()


# ============================================================================
# get_candidate_id (单用户模式)
# ============================================================================

def test_get_candidate_id_returns_default():
    """单用户工具:任何调用都返回 'default',不再按简历切分。"""
    assert get_candidate_id() == "default"


def test_get_candidate_id_is_stable():
    """多次调用一致(未来多用户切换只改这一个函数)。"""
    assert get_candidate_id() == get_candidate_id() == "default"


def test_init_db_migrates_legacy_c_prefix_to_default(tmp_path: Path):
    """init_db 应把历史上 c_xxx 格式的 candidate_id 收敛到 'default'。"""
    db = tmp_path / "test.db"
    init_db(db)

    # 直接插一行 c_xxx 模拟 alpha 测试期数据
    import sqlite3
    with sqlite3.connect(str(db)) as conn:
        conn.execute(
            "INSERT INTO interview_sessions "
            "(id, candidate_id, started_at, ended_at, level, style, "
            " jd_summary, jd_hash, score_avg, report_text, turn_count) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "legacy_001", "c_legacyhash123", "2026-07-01T00:00:00+00:00",
                "2026-07-01T00:30:00+00:00", "P5", "严谨", "jd", "h",
                None, "report", 0,
            ),
        )
        conn.commit()

    # 再调 init_db → 应触发迁移
    init_db(db)

    with sqlite3.connect(str(db)) as conn:
        sess_cid = conn.execute(
            "SELECT candidate_id FROM interview_sessions WHERE id=?",
            ("legacy_001",),
        ).fetchone()[0]
    assert sess_cid == "default"


def test_init_db_does_not_create_consent_log(tmp_path: Path):
    """ToS 已移除 → consent_log 表不应被 init_db 创建(老 DB 遗留无害)。"""
    db = tmp_path / "test.db"
    init_db(db)
    import sqlite3
    with sqlite3.connect(str(db)) as conn:
        tables = {
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert "consent_log" not in tables


# ============================================================================
# save_session + get_session roundtrip
# ============================================================================

def test_save_and_get_session_roundtrip(db: Path):
    chat, feedback, report = _sample_history()
    sid = save_session(
        db_path=db,
        level="社招(中级)",
        style="温和引导",
        jd="Python 后端 JD 内容" * 20,  # 长 JD,验证摘要
        resume_text="张三 5年 Python 后端",
        chat_history=chat,
        turn_feedback=feedback,
        report_text=report,
        started_at=datetime(2026, 7, 21, 10, 0, 0, tzinfo=timezone.utc),
    )

    sess = get_session(db, sid)
    assert sess is not None
    assert sess["id"] == sid
    assert sess["level"] == "社招(中级)"
    assert sess["style"] == "温和引导"
    assert sess["report_text"] == report
    assert sess["turn_count"] == 2  # user 消息数
    assert sess["score_avg"] == pytest.approx(6.0)
    assert len(sess["turns"]) == 4
    assert sess["turns"][0]["role"] == "assistant"
    assert sess["turns"][1]["content"] == "我做 Python 后端 5 年"
    assert len(sess["feedback"]) == 2
    assert sess["feedback"][0]["score"] == 7


def test_save_session_generates_unique_id(db: Path):
    chat, feedback, report = _sample_history()
    sid1 = save_session(
        db_path=db, level="校招", style="温和引导",
        jd="j", resume_text="r",
        chat_history=chat, turn_feedback=feedback,
        report_text=report,
        started_at=datetime.now(timezone.utc),
    )
    sid2 = save_session(
        db_path=db, level="校招", style="温和引导",
        jd="j", resume_text="r",
        chat_history=chat, turn_feedback=feedback,
        report_text=report,
        started_at=datetime.now(timezone.utc),
    )
    assert sid1 != sid2


# ============================================================================
# score_avg 边界
# ============================================================================

def test_save_session_score_avg_handles_no_feedback(db: Path):
    chat, _, report = _sample_history()
    sid = save_session(
        db_path=db, level="校招", style="温和引导",
        jd="j", resume_text="r",
        chat_history=chat, turn_feedback=[],
        report_text=report,
        started_at=datetime.now(timezone.utc),
    )
    sess = get_session(db, sid)
    assert sess["score_avg"] is None


def test_save_session_score_avg_ignores_negative_scores(db: Path):
    chat, _, report = _sample_history()
    feedback = [
        {"question": "q1", "score": 8, "advice": "ok"},
        {"question": "q2", "score": -1, "advice": ""},  # 反馈失败占位
        {"question": "q3", "score": 6, "advice": "可改"},
    ]
    sid = save_session(
        db_path=db, level="校招", style="温和引导",
        jd="j", resume_text="r",
        chat_history=chat, turn_feedback=feedback,
        report_text=report,
        started_at=datetime.now(timezone.utc),
    )
    sess = get_session(db, sid)
    # 8 + 6 / 2 = 7.0(忽略 -1)
    assert sess["score_avg"] == pytest.approx(7.0)


# ============================================================================
# list_sessions
# ============================================================================

def test_list_sessions_orders_by_ended_at_desc(db: Path):
    chat, feedback, report = _sample_history()
    sid_old = save_session(
        db_path=db, level="校招", style="温和引导",
        jd="j", resume_text="",  # 空简历 → candidate_id="default"
        chat_history=chat, turn_feedback=feedback,
        report_text=report,
        started_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
        ended_at=datetime(2026, 7, 1, 12, 0, 0, tzinfo=timezone.utc),
    )
    sid_new = save_session(
        db_path=db, level="校招", style="温和引导",
        jd="j", resume_text="",
        chat_history=chat, turn_feedback=feedback,
        report_text=report,
        started_at=datetime(2026, 7, 21, tzinfo=timezone.utc),
        ended_at=datetime(2026, 7, 21, 12, 0, 0, tzinfo=timezone.utc),
    )

    sessions = list_sessions(db, "default")
    assert len(sessions) == 2
    # 倒序:新的在前
    assert sessions[0]["id"] == sid_new
    assert sessions[1]["id"] == sid_old


def test_list_sessions_single_user_returns_all(db: Path):
    """单用户模式:不同简历的两场 session 应都列在 default bucket 下。"""
    chat, feedback, report = _sample_history()
    sid_a = save_session(
        db_path=db, level="校招", style="温和引导",
        jd="j", resume_text="简历 A",
        chat_history=chat, turn_feedback=feedback,
        report_text=report,
        started_at=datetime.now(timezone.utc),
    )
    sid_b = save_session(
        db_path=db, level="校招", style="温和引导",
        jd="j", resume_text="简历 B",
        chat_history=chat, turn_feedback=feedback,
        report_text=report,
        started_at=datetime.now(timezone.utc),
    )

    sessions = list_sessions(db, get_candidate_id())
    ids = {s["id"] for s in sessions}
    assert {sid_a, sid_b} <= ids


def test_list_sessions_respects_limit(db: Path):
    chat, feedback, report = _sample_history()
    for i in range(7):
        save_session(
            db_path=db, level="校招", style="温和引导",
            jd="j", resume_text="",  # 空简历 → "default" candidate
            chat_history=chat, turn_feedback=feedback,
            report_text=report,
            started_at=datetime(2026, 7, i + 1, tzinfo=timezone.utc),
            ended_at=datetime(2026, 7, i + 1, 12, 0, 0, tzinfo=timezone.utc),
        )
    sessions = list_sessions(db, "default", limit=5)
    assert len(sessions) == 5


# ============================================================================
# get_session 边界
# ============================================================================

def test_get_session_returns_none_for_missing(db: Path):
    assert get_session(db, "nonexistent") is None


# ============================================================================
# PII 安全
# ============================================================================

def test_no_resume_text_in_db(db: Path):
    chat, feedback, report = _sample_history()
    pii_marker = "张三_身份证_110101199001011234_PII_SECRET"
    save_session(
        db_path=db, level="校招", style="温和引导",
        jd="j", resume_text=pii_marker + " 简历其余内容",
        chat_history=chat, turn_feedback=feedback,
        report_text=report,
        started_at=datetime.now(timezone.utc),
    )

    # 全文扫描 DB,确认 PII marker 不在
    with sqlite3.connect(str(db)) as conn:
        all_text = ""
        for table in ("interview_sessions", "interview_turns", "turn_feedback"):
            rows = conn.execute(f"SELECT * FROM {table}").fetchall()
            for r in rows:
                all_text += str(r) + "\n"
    assert pii_marker not in all_text, "DB 不应存简历原文"


def test_jd_summary_truncated_to_200_chars(db: Path):
    chat, feedback, report = _sample_history()
    long_jd = "X" * 500
    sid = save_session(
        db_path=db, level="校招", style="温和引导",
        jd=long_jd, resume_text="r",
        chat_history=chat, turn_feedback=feedback,
        report_text=report,
        started_at=datetime.now(timezone.utc),
    )
    sess = get_session(db, sid)
    # jd_summary ≤ 200 字(以 … 结尾或原长 <200)
    assert len(sess["jd_summary"]) <= 201


# ============================================================================
# module-level constants
# ============================================================================

def test_default_db_path_is_in_data_dir():
    assert DEFAULT_DB_PATH.name == "interviews.db"
    assert DEFAULT_DB_PATH.parent.name == "data"

# ============================================================================
# mode 列 (v0.3.1 专项练习)
# ============================================================================

def test_save_session_defaults_mode_to_interview(db: Path):
    """不传 mode → 落 'interview'(向后兼容)。"""
    chat, feedback, report = _sample_history()
    sid = save_session(
        db_path=db,
        level="社招(中级)",
        style="温和引导",
        jd="JD",
        resume_text="",
        chat_history=chat,
        turn_feedback=feedback,
        report_text=report,
        started_at=datetime.now(timezone.utc),
    )
    rows = list_sessions(db, get_candidate_id(), limit=5)
    assert rows[0]["id"] == sid
    assert rows[0]["mode"] == "interview"


def test_save_session_accepts_practice_mode(db: Path):
    """mode='practice' 应原样落库,并被 list_sessions 带出。"""
    chat, feedback, report = _sample_history()
    save_session(
        db_path=db,
        level="社招(高级)",
        style="压力深挖",
        jd="",
        resume_text="",
        chat_history=chat,
        turn_feedback=feedback,
        report_text=report,
        started_at=datetime.now(timezone.utc),
        mode="practice",
    )
    rows = list_sessions(db, get_candidate_id(), limit=5)
    assert rows[0]["mode"] == "practice"


def test_init_db_adds_mode_column_to_legacy_db(tmp_path: Path):
    """老 DB(无 mode 列)init_db 应幂等 ALTER TABLE 补列,已有行 backfill。"""
    p = tmp_path / "legacy.db"
    p.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(p)) as conn:
        conn.execute(
            """
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
            )
            """
        )
        conn.execute(
            "INSERT INTO interview_sessions VALUES "
            "('old1','default','t','t','校招','温和引导','jd','h',6.0,'r',2)"
        )

    init_db(p)

    with sqlite3.connect(str(p)) as conn:
        cols = {r[1] for r in conn.execute(
            "PRAGMA table_info('interview_sessions')"
        ).fetchall()}
        assert "mode" in cols
        mode = conn.execute(
            "SELECT mode FROM interview_sessions WHERE id='old1'"
        ).fetchone()[0]
    assert mode == "interview", f"老行应 backfill 为 interview,实际: {mode}"

    # 幂等:再跑一次不炸
    init_db(p)
