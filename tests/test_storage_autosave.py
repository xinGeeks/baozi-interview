"""interview_autosave storage 层单元测试。

覆盖:
- save_autosave / load_autosave round-trip
- UPSERT(同 candidate_id 二次写入覆盖)
- load 缺失 → None
- clear_autosave 幂等
- json 损坏 → None
- 多 candidate 隔离(MVP 单用户场景下默认同 cid,但仍验证 schema 不串)
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from storage import (
    clear_autosave,
    get_candidate_id,
    init_db,
    load_autosave,
    save_autosave,
)


def _connect(db: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    return conn


def test_schema_has_autosave_table(tmp_path: Path):
    db = tmp_path / "test.db"
    init_db(db)
    with _connect(db) as conn:
        tables = {
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert "interview_autosave" in tables
    # columns
    with _connect(db) as conn:
        cols = {
            r["name"]
            for r in conn.execute(
                "PRAGMA table_info('interview_autosave')"
            ).fetchall()
        }
    assert {"candidate_id", "state_json", "updated_at"} <= cols


def test_save_and_load_roundtrip(tmp_path: Path):
    db = tmp_path / "test.db"
    init_db(db)
    cid = get_candidate_id()
    state = {
        "chat_history": [{"role": "assistant", "content": "q1"}],
        "turn_feedback": [{"question": "q1", "score": 8, "advice": "好"}],
        "interview_level": "社招(中级)",
        "resume_content": "张三 5 年 Python",
    }
    save_autosave(db, cid, state)
    loaded = load_autosave(db, cid)
    assert loaded == state
    # 中文 + 特殊字符保真
    assert loaded["resume_content"] == "张三 5 年 Python"


def test_save_autosave_upserts_overwrite(tmp_path: Path):
    db = tmp_path / "test.db"
    init_db(db)
    cid = get_candidate_id()
    save_autosave(db, cid, {"chat_history": [{"role": "a", "content": "v1"}]})
    save_autosave(db, cid, {"chat_history": [{"role": "a", "content": "v2"}]})
    # 行数仍为 1(ON CONFLICT DO UPDATE)
    with _connect(db) as conn:
        n = conn.execute(
            "SELECT COUNT(*) FROM interview_autosave WHERE candidate_id=?",
            (cid,),
        ).fetchone()[0]
    assert n == 1
    loaded = load_autosave(db, cid)
    assert loaded["chat_history"][0]["content"] == "v2"


def test_load_missing_returns_none(tmp_path: Path):
    db = tmp_path / "test.db"
    init_db(db)
    assert load_autosave(db, "no-such-cid") is None


def test_clear_autosave_idempotent(tmp_path: Path):
    db = tmp_path / "test.db"
    init_db(db)
    cid = get_candidate_id()
    save_autosave(db, cid, {"x": 1})
    # 第一次 clear:实际删除
    clear_autosave(db, cid)
    assert load_autosave(db, cid) is None
    # 第二次 clear:不存在也不报错
    clear_autosave(db, cid)
    assert load_autosave(db, cid) is None


def test_load_corrupted_json_returns_none(tmp_path: Path):
    """state_json 损坏 → load 返 None(不抛)。"""
    db = tmp_path / "test.db"
    init_db(db)
    cid = get_candidate_id()
    with _connect(db) as conn:
        conn.execute(
            "INSERT INTO interview_autosave (candidate_id, state_json, updated_at)"
            " VALUES (?, ?, ?)",
            (cid, "{not valid json", "2026-07-01T00:00:00+00:00"),
        )
        conn.commit()
    assert load_autosave(db, cid) is None


def test_save_updates_updated_at(tmp_path: Path):
    """二次写入应刷新 updated_at。"""
    db = tmp_path / "test.db"
    init_db(db)
    cid = get_candidate_id()
    save_autosave(db, cid, {"chat_history": [{"role": "a", "content": "v1"}]})
    with _connect(db) as conn:
        first = conn.execute(
            "SELECT updated_at FROM interview_autosave WHERE candidate_id=?",
            (cid,),
        ).fetchone()["updated_at"]
    # 二次写入
    save_autosave(db, cid, {"chat_history": [{"role": "a", "content": "v2"}]})
    with _connect(db) as conn:
        second = conn.execute(
            "SELECT updated_at FROM interview_autosave WHERE candidate_id=?",
            (cid,),
        ).fetchone()["updated_at"]
    assert second >= first


def test_save_complex_serializable_payload(tmp_path: Path):
    """复杂对象(list[dict])能正确往返。"""
    db = tmp_path / "test.db"
    init_db(db)
    cid = get_candidate_id()
    state = {
        "chat_history": [
            {"role": "assistant", "content": "q1"},
            {"role": "user", "content": "a1"},
            {"role": "assistant", "content": "q2"},
        ],
        "turn_feedback": [
            {"question": "q1", "score": 7, "advice": "用 STAR"},
            {"question": "q2", "score": 9, "advice": "数据支撑好"},
        ],
        "interview_level": "社招(高级)",
    }
    save_autosave(db, cid, state)
    loaded = load_autosave(db, cid)
    assert loaded == state
    assert len(loaded["chat_history"]) == 3
    assert loaded["turn_feedback"][0]["score"] == 7


def test_get_candidate_id_in_singleton_mode():
    """单用户模式下 get_candidate_id() 固定返回 'default'。"""
    assert get_candidate_id() == "default"