"""storage.py topic 扩展的单元 + 集成测试。

覆盖:
- init_db 创建新表,不破坏旧表
- write_topic_facts 幂等(INSERT OR IGNORE)
- write_candidate_topic_cache UPSERT
- get_topics_for_candidate 排序
- get_topic_trend 跨 session 排序
- extract_and_store_for_session 端到端
- 失败隔离(extract 抛错时返回 0,不冒泡)
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from storage import (
    backfill_topics_for_candidate,
    extract_and_store_for_session,
    get_candidate_id,
    get_session,
    get_topic_trend,
    get_topics_for_candidate,
    init_db,
    save_session,
    write_candidate_topic_cache,
    write_topic_facts,
)
from topic_extraction import TopicFact


# ============================================================================
# Fixtures + helpers
# ============================================================================


@pytest.fixture
def db(tmp_path: Path) -> Path:
    p = tmp_path / "test.db"
    init_db(p)
    return p


def _save_simple_session(db: Path, *, num_user_turns: int = 4) -> str:
    """save 一个最简单的 session,返回 sid。"""
    chat: list[dict] = []
    for i in range(num_user_turns):
        chat.append({"role": "assistant", "content": f"question {i}"})
        chat.append({
            "role": "user",
            "content": "redis 缓存 kafka 消息队列 redis 缓存 kafka 消息队列",
        })
    feedback = [
        {"question": f"q{i}", "score": 5, "advice": ""}
        for i in range(num_user_turns)
    ]
    return save_session(
        db_path=db,
        level="P5",
        style="温和",
        jd="后端",
        resume_text="",
        chat_history=chat,
        turn_feedback=feedback,
        report_text="报告",
        started_at=datetime.now(timezone.utc),
    )


# ============================================================================
# 2.1 / 2.7 init_db 幂等
# ============================================================================


def test_init_db_creates_topic_tables(db: Path):
    with sqlite3.connect(str(db)) as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name IN ('topic_facts', 'candidate_topic_cache')"
        ).fetchall()
    names = {r[0] for r in rows}
    assert "topic_facts" in names
    assert "candidate_topic_cache" in names


def test_init_db_preserves_existing_v03_tables(tmp_path: Path):
    """v0.3 风格的 4 表 DB → init_db 后旧表数据 100% 保留 + 新表被加。"""
    db = tmp_path / "legacy.db"
    # 手工建 v0.3 风格的 4 表 + 一行示例数据
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

    # init_db 应幂等地加新表且不破坏旧数据
    init_db(db)

    with sqlite3.connect(str(db)) as conn:
        legacy = conn.execute(
            "SELECT id, score_avg FROM interview_sessions WHERE id='legacy1'"
        ).fetchone()
        assert legacy[0] == "legacy1"
        assert legacy[1] == 7.0
        # 新表也加了
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert "topic_facts" in tables
    assert "candidate_topic_cache" in tables


# ============================================================================
# 2.2 write_topic_facts 幂等
# ============================================================================


def test_write_topic_facts_inserts_rows(db: Path):
    sid = _save_simple_session(db)
    topics = [
        TopicFact(topic="redis", score=0.1, source_turn=1),
        TopicFact(topic="kafka", score=0.1, source_turn=3),
    ]
    n = write_topic_facts(db, sid, topics)
    assert n == 2

    with sqlite3.connect(str(db)) as conn:
        rows = conn.execute(
            "SELECT topic FROM topic_facts WHERE sid=?", (sid,)
        ).fetchall()
    assert {r[0] for r in rows} == {"redis", "kafka"}


def test_write_topic_facts_idempotent(db: Path):
    sid = _save_simple_session(db)
    topics = [TopicFact(topic="redis", score=0.1, source_turn=1)]
    # 第二次写入同 (sid, topic, source_turn) → rowcount=0
    write_topic_facts(db, sid, topics)
    n2 = write_topic_facts(db, sid, topics)
    assert n2 == 0

    with sqlite3.connect(str(db)) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM topic_facts WHERE sid=?", (sid,)
        ).fetchone()[0]
    assert count == 1


def test_write_topic_facts_empty_list_is_noop(db: Path):
    sid = _save_simple_session(db)
    assert write_topic_facts(db, sid, []) == 0


# ============================================================================
# 2.3 write_candidate_topic_cache UPSERT
# ============================================================================


def test_write_candidate_topic_cache_insert(db: Path):
    topics = [TopicFact(topic="redis", score=0.2, source_turn=0)]
    n = write_candidate_topic_cache(db, "default", topics)
    assert n == 1
    with sqlite3.connect(str(db)) as conn:
        row = conn.execute(
            "SELECT score FROM candidate_topic_cache "
            "WHERE candidate_id='default' AND topic='redis'"
        ).fetchone()
    assert row[0] == 0.2


def test_write_candidate_topic_cache_upsert_updates_score_to_max(
    db: Path,
):
    # 第一次插入 score=0.2
    write_candidate_topic_cache(
        db,
        "default",
        [TopicFact(topic="redis", score=0.2, source_turn=0)],
        last_seen_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    # 第二次插入 score=0.5(更大)
    write_candidate_topic_cache(
        db,
        "default",
        [TopicFact(topic="redis", score=0.5, source_turn=0)],
        last_seen_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )
    with sqlite3.connect(str(db)) as conn:
        row = conn.execute(
            "SELECT score, last_seen_at FROM candidate_topic_cache "
            "WHERE candidate_id='default' AND topic='redis'"
        ).fetchone()
    assert row[0] == 0.5  # MAX 保留
    assert "2026-06-01" in row[1]


def test_write_candidate_topic_cache_upsert_keeps_higher_score(
    db: Path,
):
    """新 score 更小 → 保留旧 score(MAX semantics)。"""
    write_candidate_topic_cache(
        db, "default",
        [TopicFact(topic="redis", score=0.8, source_turn=0)],
    )
    write_candidate_topic_cache(
        db, "default",
        [TopicFact(topic="redis", score=0.3, source_turn=0)],
    )
    with sqlite3.connect(str(db)) as conn:
        row = conn.execute(
            "SELECT score FROM candidate_topic_cache "
            "WHERE candidate_id='default' AND topic='redis'"
        ).fetchone()
    assert row[0] == 0.8


def test_write_candidate_topic_cache_dedupes_per_call(db: Path):
    """一次 batch 中同 topic 多次出现 → 取 MAX 写一次。"""
    topics = [
        TopicFact(topic="redis", score=0.1, source_turn=0),
        TopicFact(topic="redis", score=0.3, source_turn=2),
        TopicFact(topic="redis", score=0.2, source_turn=4),
    ]
    write_candidate_topic_cache(db, "default", topics)
    with sqlite3.connect(str(db)) as conn:
        rows = conn.execute(
            "SELECT score FROM candidate_topic_cache WHERE topic='redis'"
        ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == 0.3


# ============================================================================
# 2.4 get_topics_for_candidate 排序
# ============================================================================


def test_get_topics_for_candidate_sort_score_desc(db: Path):
    write_candidate_topic_cache(
        db, "default",
        [
            TopicFact(topic="low", score=0.1, source_turn=0),
            TopicFact(topic="high", score=0.9, source_turn=0),
            TopicFact(topic="mid", score=0.5, source_turn=0),
        ],
    )
    topics = get_topics_for_candidate(db, "default")
    assert [t.topic for t in topics] == ["high", "mid", "low"]


def test_get_topics_for_candidate_tiebreak_topic_asc(db: Path):
    write_candidate_topic_cache(
        db, "default",
        [
            TopicFact(topic="C", score=0.5, source_turn=0),
            TopicFact(topic="A", score=0.5, source_turn=0),
            TopicFact(topic="B", score=0.5, source_turn=0),
        ],
    )
    topics = get_topics_for_candidate(db, "default")
    assert [t.topic for t in topics] == ["A", "B", "C"]


def test_get_topics_for_candidate_empty_for_unknown_candidate(db: Path):
    assert get_topics_for_candidate(db, "unknown") == []


# ============================================================================
# 2.5 get_topic_trend 跨 session
# ============================================================================


def test_get_topic_trend_per_session_ordered_by_ended_at(db: Path):
    # 写 2 个 session,各产生一个 topic_facts 行
    sid1 = _save_simple_session(db, num_user_turns=3)
    sid2 = _save_simple_session(db, num_user_turns=3)
    write_topic_facts(
        db, sid1,
        [TopicFact(topic="redis", score=0.2, source_turn=1)],
    )
    write_topic_facts(
        db, sid2,
        [TopicFact(topic="redis", score=0.3, source_turn=1)],
    )
    # sid1 ended_at < sid2 ended_at
    trend = get_topic_trend(db, "default", "redis")
    assert len(trend) == 2
    # 顺序按 ended_at ASC
    assert trend[0][0] == sid1
    assert trend[1][0] == sid2
    assert trend[0][1] == 0.2
    assert trend[1][1] == 0.3


def test_get_topic_trend_unknown_topic_returns_empty(db: Path):
    assert get_topic_trend(db, "default", "never_existed") == []


def test_get_topic_trend_unknown_topic_returns_empty(db: Path):
    assert get_topic_trend(db, "default", "never_existed") == []


def test_get_topic_trend_filters_by_candidate_via_join(db: Path):
    """FK 约束阻止 orphan topic_facts → 用真实 session 验证 JOIN 行为。

    两个 candidate 各开一个 session,都抽取 "redis" topic;trend 只返回该 candidate 的。
    """
    # candidate = "default" 的 session
    sid1 = _save_simple_session(db, num_user_turns=3)
    write_topic_facts(
        db, sid1,
        [TopicFact(topic="redis", score=0.2, source_turn=1)],
    )
    # 另一个 candidate 的 session:手工 insert interview_sessions + turns
    sid2 = "other-sid"
    with sqlite3.connect(str(db)) as conn:
        conn.execute(
            """INSERT INTO interview_sessions
               (id, candidate_id, started_at, ended_at, level, style,
                jd_summary, jd_hash, score_avg, report_text, turn_count)
               VALUES (?, 'other-user', ?, ?, 'P5', '温和', 'jd', 'h',
                       7.0, 'r', 1)""",
            (sid2, "2026-01-01T00:00:00+00:00", "2026-01-01T01:00:00+00:00"),
        )
        conn.execute(
            """INSERT INTO interview_turns
               (session_id, turn_idx, role, content)
               VALUES (?, 0, 'user', 'redis redis redis redis')""",
            (sid2,),
        )
        conn.commit()
    # 这里 FK sid→interview_sessions 已满足,但 candidate_id != 'default'
    # INSERT OR IGNORE 会通过(因为 (sid, topic, source_turn) PK 不冲突)
    write_topic_facts(
        db, sid2,
        [TopicFact(topic="redis", score=0.5, source_turn=0)],
    )

    # default candidate 只看到 sid1
    default_trend = get_topic_trend(db, "default", "redis")
    assert len(default_trend) == 1
    assert default_trend[0][0] == sid1
    assert default_trend[0][1] == 0.2

    # other-user 看到 sid2
    other_trend = get_topic_trend(db, "other-user", "redis")
    assert len(other_trend) == 1
    assert other_trend[0][0] == sid2


# ============================================================================
# 2.6 / 2.7 extract_and_store_for_session 端到端
# ============================================================================


def test_backfill_topics_for_candidate_is_idempotent_and_skips_practice(
    db: Path,
):
    sid_interview = _save_simple_session(db)
    sid_practice = save_session(
        db_path=db,
        level="P5",
        style="温和",
        jd="后端",
        resume_text="",
        chat_history=[
            {"role": "user", "content": "redis 缓存 kafka 消息队列 redis"},
        ],
        turn_feedback=[],
        report_text="报告",
        started_at=datetime.now(timezone.utc),
        mode="practice",
    )

    assert backfill_topics_for_candidate(db, "default") == 1
    assert get_topics_for_candidate(db, "default")

    with sqlite3.connect(str(db)) as conn:
        first_facts = conn.execute(
            "SELECT COUNT(*) FROM topic_facts"
        ).fetchone()[0]
        practice_facts = conn.execute(
            "SELECT COUNT(*) FROM topic_facts WHERE sid=?", (sid_practice,)
        ).fetchone()[0]
        interview_facts = conn.execute(
            "SELECT COUNT(*) FROM topic_facts WHERE sid=?", (sid_interview,)
        ).fetchone()[0]

    assert first_facts == interview_facts
    assert practice_facts == 0
    assert backfill_topics_for_candidate(db, "default") == 0

    with sqlite3.connect(str(db)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM topic_facts").fetchone()[0] == first_facts


def test_extract_and_store_for_session_unknown_sid_returns_zero(db: Path):
    n = extract_and_store_for_session(db, "nonexistent_sid", "default")
    assert n == 0


def test_extract_and_store_for_session_no_user_turns_returns_zero(
    db: Path,
):
    # save 一个只有 assistant turn 的 session
    sid = save_session(
        db_path=db,
        level="P5",
        style="温和",
        jd="",
        resume_text="",
        chat_history=[{"role": "assistant", "content": "hello"}],
        turn_feedback=[],
        report_text="r",
        started_at=datetime.now(timezone.utc),
    )
    n = extract_and_store_for_session(db, sid, "default")
    assert n == 0


def test_extract_and_store_for_session_failure_isolation(db: Path):
    """extract 抛错时 orchestrator 吞掉异常,返回 0,不冒泡。"""
    sid = _save_simple_session(db, num_user_turns=3)
    # monkeypatch topic_extraction.extract_topics 让它抛错
    import topic_extraction
    orig = topic_extraction.extract_topics
    def boom(*a, **kw):
        raise RuntimeError("simulated crash")
    topic_extraction.extract_topics = boom
    try:
        n = extract_and_store_for_session(db, sid, "default")
        assert n == 0  # 不冒泡
    finally:
        topic_extraction.extract_topics = orig

    # 主 session 数据未受影响
    sess = get_session(db, sid)
    assert sess is not None
    assert sess["id"] == sid