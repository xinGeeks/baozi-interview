"""app.py 弱 topic 专项练习 AppTest 集成测试。

覆盖:
- 1.1 sidebar 出现 practice expander(默认折叠)
- 1.2 点 practice candidate button → practice_mode=True, practice_topic 设置,
       触发 auto-start → chat_input 出现
- 1.3 退出按钮 / 输入『退出专项训练』→ save_session 用 mode='practice',
       practice_mode 重置
- 1.4 正常 interview 仍保存为 mode='interview' 且 extract 仍跑
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from storage import (
    get_topics_for_candidate,
    init_db,
    save_session,
    write_candidate_topic_cache,
)
from topic_extraction import TopicFact


# ============================================================================
# Helpers
# ============================================================================


def _make_app(responses: list[str], *, db_path: Path) -> AppTest:
    """构造 AppTest,绑独立 DB(通过 env var STORAGE_DB_PATH)。"""
    os.environ["STORAGE_DB_PATH"] = str(db_path)
    init_db(db_path)
    at = AppTest.from_file("app.py", default_timeout=60)
    at.session_state["tos_accepted"] = True
    at.session_state["tos_check_done"] = True
    at.run()
    at.session_state["mock_responses"] = list(responses)
    return at


def _ss_get(at: AppTest, key: str, default=None):
    """AppTest 的 at.session_state 不支持 .get(),用 in 检查包装。"""
    return at.session_state[key] if key in at.session_state else default


def _seed_topic_cache(db: Path, topic: str = "kafka", score: float = 0.6) -> None:
    """直接预填 candidate_topic_cache 让 sidebar practice 列表有内容。"""
    init_db(db)  # 表不存在时建表
    write_candidate_topic_cache(
        db, "default",
        [TopicFact(topic=topic, score=score, source_turn=0)],
    )


# ============================================================================
# 1.1 Sidebar expander 存在
# ============================================================================


def test_practice_expander_present_in_sidebar(tmp_path: Path):
    db = tmp_path / "test.db"
    at = _make_app([], db_path=db)
    found = False
    for el in at.sidebar:
        if getattr(el, "label", "") and "弱 topic 专项练习" in str(el.label):
            found = True
            break
    assert found, "expected 弱 topic 专项练习 expander in sidebar"


def test_practice_expander_empty_state_message(tmp_path: Path):
    """空态:cache 无内容 → 显示『先完成 1-2 场面试』提示。"""
    db = tmp_path / "test.db"
    at = _make_app([], db_path=db)
    found = False
    for el in at.sidebar:
        body = getattr(el, "body", None)
        if body and "先完成 1-2 场面试" in str(body):
            found = True
            break
    assert found, "expected empty-state caption in practice expander"


# ============================================================================
# 1.2 Entry:点 candidate button → auto-start interview
# ============================================================================


def test_practice_entry_starts_chat_with_topic_focus(tmp_path: Path):
    """点 sidebar practice candidate button → practice_mode + practice_topic
    设置,auto-start 触发 chat_input 渲染。
    """
    db = tmp_path / "test.db"
    _seed_topic_cache(db, topic="kafka", score=0.6)
    # mock:第一题 + 后续若干题(允许用户输入)
    at = _make_app(
        ["q1", "q2", "q3", "q4"],
        db_path=db,
    )

    # 找 practice_entry_kafka button
    practice_btns = [
        b for b in at.sidebar
        if str(b.key).startswith("practice_entry_")
    ]
    assert practice_btns, "no practice entry button rendered"
    btn = practice_btns[0]
    btn.click()
    at.run()

    # practice_mode + practice_topic 已设
    assert _ss_get(at, "practice_mode") is True
    assert _ss_get(at, "practice_topic") == "kafka"
    # auto-start 触发:interview_started=True + chat_input 出现
    assert _ss_get(at, "interview_started") is True
    assert len(at.chat_input) == 1, "auto-start should render chat_input"


# ============================================================================
# 1.3 Exit:退出按钮触发 save with mode='practice'
# ============================================================================


def test_practice_exit_via_button_saves_with_practice_mode(tmp_path: Path):
    """完整跑一次 practice,点退出 → save_session 用 mode='practice',
    candidate cache 不被污染。
    """
    db = tmp_path / "test.db"
    _seed_topic_cache(db, topic="kafka", score=0.6)
    # mock:首题(generate_report 调一次)+ 后续题
    at = _make_app(
        ["q1", "q2", "q3", "q4", "report_text"],
        db_path=db,
    )

    # 进入 practice
    practice_btns = [
        b for b in at.sidebar
        if str(b.key).startswith("practice_entry_")
    ]
    practice_btns[0].click()
    at.run()

    # 输入 2 轮后点退出
    assert _ss_get(at, "interview_started") is True
    at.chat_input[0].set_value("kafka 高吞吐")
    at.run()
    at.chat_input[0].set_value("kafka 消费")
    at.run()

    # 点退出按钮
    exit_btns = [b for b in at.button if str(b.key) == "exit_practice"]
    assert exit_btns, "no exit_practice button"
    exit_btns[0].click()
    at.run()

    # 验证 mode 列
    with sqlite3.connect(str(db)) as conn:
        rows = conn.execute(
            "SELECT id, mode FROM interview_sessions"
        ).fetchall()
    assert len(rows) == 1
    assert rows[0][1] == "practice"

    # practice_mode 已重置
    assert _ss_get(at, "practice_mode") is False
    assert _ss_get(at, "practice_topic") == ""

    # cache 仍只有 seed 注入的 1 个 topic(没被 practice transcript 污染)
    topics = get_topics_for_candidate(db, "default")
    assert len(topics) == 1
    assert topics[0].topic == "kafka"


def test_practice_exit_via_text_signal(tmp_path: Path):
    """用户输入『退出专项训练』→ 同样触发 _generate_report + 清 practice_mode。"""
    db = tmp_path / "test.db"
    _seed_topic_cache(db, topic="kafka", score=0.6)
    at = _make_app(
        ["q1", "q2", "q3", "report_text"],
        db_path=db,
    )

    practice_btns = [
        b for b in at.sidebar
        if str(b.key).startswith("practice_entry_")
    ]
    practice_btns[0].click()
    at.run()

    # 直接输入『退出专项训练』
    at.chat_input[0].set_value("好的,退出专项训练")
    at.run()

    with sqlite3.connect(str(db)) as conn:
        rows = conn.execute(
            "SELECT mode FROM interview_sessions"
        ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "practice"
    assert _ss_get(at, "practice_mode") is False


# ============================================================================
# 1.4 正常 interview 模式不被 practice 改动影响
# ============================================================================


def test_interview_mode_not_affected_by_practice_changes(tmp_path: Path):
    """走正常 开始面试 → save 用 mode='interview',extract 仍跑。"""
    db = tmp_path / "test.db"
    os.environ["STORAGE_DB_PATH"] = str(db)
    init_db(db)
    # 5 轮对话 + 报告生成 = 5-6 个 at.run(),每次 10-15s → 需 120s per-call
    at = AppTest.from_file("app.py", default_timeout=120)
    at.session_state["tos_accepted"] = True
    at.session_state["tos_check_done"] = True
    at.run()
    at.session_state["mock_responses"] = [
        "q1", "q2", "q3", "q4", "report_text"
    ]

    # 填 JD
    at.text_area[0].set_value("Python 后端开发")
    # 找开始面试 button(不含『重新』)
    start_btn = next(
        b for b in at.button
        if "开始面试" in str(b.label) and "重新" not in str(b.label)
    )
    start_btn.click()
    at.run()

    # 4 轮对话
    at.chat_input[0].set_value("redis 缓存 kafka 消息队列 redis 缓存")
    at.run()
    at.chat_input[0].set_value("redis 缓存 kafka 消息队列 redis 缓存")
    at.run()
    at.chat_input[0].set_value("redis 缓存 kafka 消息队列 redis 缓存")
    at.run()
    from prompts import END_SIGNAL
    at.chat_input[0].set_value(f"好的,{END_SIGNAL}")
    at.run()

    # mode='interview'
    with sqlite3.connect(str(db)) as conn:
        rows = conn.execute(
            "SELECT mode FROM interview_sessions"
        ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "interview"
    # extract 跑了 → cache 有数据
    topics = get_topics_for_candidate(db, "default")
    assert len(topics) >= 1


# ============================================================================
# 1.5 练习记录 subsection
# ============================================================================


def test_practice_history_subsection_renders(tmp_path: Path):
    """有 practice session 时,sidebar 出现『练习记录』子区。"""
    db = tmp_path / "test.db"
    # 手工塞 1 条 practice session
    init_db(db)
    chat = [
        {"role": "assistant", "content": "q1"},
        {"role": "user", "content": "kafka 高吞吐"},
    ]
    save_session(
        db_path=db, level="P5", style="温和", jd="", resume_text="",
        chat_history=chat, turn_feedback=[],
        report_text="r", started_at=datetime.now(timezone.utc),
        mode="practice",
    )
    at = _make_app([], db_path=db)

    found = False
    for el in at.sidebar:
        if (
            getattr(el, "label", "")
            and "练习记录" in str(el.label)
        ):
            found = True
            break
    assert found, "expected 练习记录 sub-expander in sidebar"
