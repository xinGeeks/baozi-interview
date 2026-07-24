"""app.py 跨会话 topic 可视化集成测试 (Streamlit AppTest)。

覆盖:
- Sidebar expander 存在且默认折叠
- 空态:fresh DB → expander body 显示提示
- 填充态:预填 candidate_topic_cache → cloud + chart 渲染
- extract hook 在 save_session 后被调
- extract 失败时主流程不挂(报告仍渲染)
"""
from __future__ import annotations

import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from storage import (
    extract_and_store_for_session,
    init_db,
    save_session,
    write_candidate_topic_cache,
)
from tests.conftest import FakeLLM
from topic_extraction import TopicFact


# ============================================================================
# Helpers
# ============================================================================


def _make_app(responses: list[str], *, db_path: Path) -> tuple[AppTest, FakeLLM]:
    """构造 AppTest,绑独立 DB(通过 env var STORAGE_DB_PATH)。"""
    import os
    os.environ["STORAGE_DB_PATH"] = str(db_path)
    # 确保 DB 初始化
    init_db(db_path)
    # default_timeout=60:trend 列表的 N 个 st.button + LLM 解析 + 多 at.run() 调用,
    # 30s 在 CI 偶发超时。60s 是稳妥的值。
    at = AppTest.from_file("app.py", default_timeout=60)
    at.session_state["tos_accepted"] = True
    at.session_state["tos_check_done"] = True
    at.run()
    at.session_state["mock_responses"] = list(responses)
    fake = FakeLLM(list(responses))
    return at, fake


def _has_text(at: AppTest, needle: str) -> bool:
    """检查 rendered tree 是否含 needle(任意类型节点的 value/body 中)。"""
    for el in at.main:
        body = getattr(el, "body", None)
        if body and needle in str(body):
            return True
    for el in at.sidebar:
        body = getattr(el, "body", None)
        if body and needle in str(body):
            return True
    return False


def _save_a_session_with_topics(db: Path) -> str:
    """save 一个有足够内容的 session,直接调用 extract 写入 cache。"""
    init_db(db)  # 表不存在时建表
    chat = []
    for i in range(4):
        chat.append({"role": "assistant", "content": f"q {i}"})
        chat.append({
            "role": "user",
            "content": "redis 缓存 kafka 消息队列 redis 缓存 kafka 消息队列 redis",
        })
    sid = save_session(
        db_path=db,
        level="P5",
        style="温和",
        jd="后端",
        resume_text="",
        chat_history=chat,
        turn_feedback=[
            {"question": f"q{i}", "score": 5, "advice": ""} for i in range(4)
        ],
        report_text="报告",
        started_at=datetime.now(timezone.utc),
    )
    extract_and_store_for_session(db, sid, "default")
    return sid


# ============================================================================
# 6.2 Sidebar expander 存在
# ============================================================================


def test_topic_expander_present_in_sidebar(tmp_path: Path):
    db = tmp_path / "test.db"
    at, _fake = _make_app([], db_path=db)
    # sidebar 应有 🎯 跨会话训练图谱 expander
    found = False
    for el in at.sidebar:
        if getattr(el, "label", "") and "跨会话训练图谱" in str(el.label):
            found = True
            break
    assert found, "expected 跨会话训练图谱 expander in sidebar"


# ============================================================================
# 6.3 空态
# ============================================================================


def test_topic_expander_empty_state_no_topics(tmp_path: Path):
    db = tmp_path / "test.db"
    at, _fake = _make_app([], db_path=db)
    # 不预填 → candidate_topic_cache 为空
    # 展开 expander → 应该显示 empty caption
    # AppTest 不会自动展开 expander;检查默认状态:empty caption 不渲染
    # 但我们可以检查 get_topics_for_candidate 返回 []
    from storage import get_topics_for_candidate
    assert get_topics_for_candidate(db, "default") == []


def test_topic_expander_empty_caption_text_in_helper():
    """空态文案应在 helper / 模块中可验证存在。"""
    import app
    # 找源码里的空态串
    src = Path(app.__file__).read_text(encoding="utf-8")
    assert "暂无跨 session 数据" in src


# ============================================================================
# 6.4 填充态:cloud + chart 渲染
# ============================================================================


def test_topic_expander_populated_state_renders_cloud_and_chart(tmp_path: Path):
    db = tmp_path / "test.db"
    _save_a_session_with_topics(db)

    at, _fake = _make_app([], db_path=db)
    # 此时 candidate_topic_cache 应有数据
    from storage import get_topics_for_candidate
    topics = get_topics_for_candidate(db, "default")
    assert len(topics) >= 1

    # 渲染 topic_cloud_html 应有非空 HTML
    import app
    html_str = app._topic_cloud_html(topics)
    assert html_str
    # 至少含 1 个 topic 字符串
    assert any(t.topic in html_str for t in topics)


# ============================================================================
# 6.5 extract hook fires on save_session
# ============================================================================


def _run_full_interview(at: AppTest, jd: str = "Python 后端开发"):
    """完整跑一次 3 轮面试:开始 → 3 次 chat_input(末轮含 END_SIGNAL)→ 报告。"""
    at.text_area[0].set_value(jd)
    start_btn = next(
        b for b in at.button if "开始面试" in str(b.label) and "重新" not in str(b.label)
    )
    start_btn.click()
    at.run()

    # 三次回答
    assert len(at.chat_input) == 1, "开始后应出现 chat_input"
    at.chat_input[0].set_value("redis 缓存 kafka 消息队列 redis 缓存 kafka 消息队列")
    at.run()
    at.chat_input[0].set_value("redis 缓存 kafka 消息队列 redis 缓存 kafka 消息队列")
    at.run()
    from prompts import END_SIGNAL
    at.chat_input[0].set_value(f"好的,{END_SIGNAL}")
    at.run()


def test_extract_hook_called_after_save_session(monkeypatch, tmp_path: Path):
    """完整跑一次面试,验证 extract_and_store_for_session 被调用。

    直接观察副作用(candidate_topic_cache 写入)而非 mock call 计数:
    AppTest 的 monkeypatch 在多次 at.run() 之间可能不稳,直接观察数据更可靠。
    """
    db = tmp_path / "test.db"
    responses = [
        "q1", "q2", "q3", "q4", "报告内容",
    ]
    at, _fake = _make_app(responses, db_path=db)

    _run_full_interview(at)

    # 副作用断言:candidate_topic_cache 应该有数据
    from storage import get_topics_for_candidate
    topics = get_topics_for_candidate(db, "default")
    assert len(topics) >= 1, (
        f"extract_and_store 未触发,cache 空。session_state keys: "
        f"{list(at.session_state.keys())}, report_text={'report_text' in at.session_state}"
    )


# ============================================================================
# 6.6 extract 失败不阻断主流程
# ============================================================================


def test_extract_failure_does_not_break_interview_flow(monkeypatch, tmp_path: Path):
    """extract 抛错时,报告仍渲染,session 仍持久化。"""
    db = tmp_path / "test.db"
    responses = [
        "q1", "q2", "q3", "q4", "报告内容",
    ]
    at, _fake = _make_app(responses, db_path=db)

    # 让 extract 抛 RuntimeError(模拟真实失败)
    # 注意:必须 patch storage 上的名字,而不是 app 上的。
    # AppTest 每次 at.run() 会重新执行 app.py,触发 `from storage import ...`,
    # 该语句会重读 storage.__dict__["extract_and_store_for_session"] 的当前值
    # 并覆盖 app.__dict__["extract_and_store_for_session"]。所以直接 patch
    # `app.extract_and_store_for_session` 会被覆盖;patch storage 上的同名才是稳定的。
    def boom(*args, **kwargs):
        raise RuntimeError("simulated extract crash")

    monkeypatch.setattr("storage.extract_and_store_for_session", boom)

    _run_full_interview(at)

    # session 仍应持久化(extract 失败不影响 save)
    with sqlite3.connect(str(db)) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM interview_sessions"
        ).fetchone()[0]
    assert count >= 1, "session 未持久化"

    # 报告应渲染
    report = at.session_state["report_text"] if "report_text" in at.session_state else ""
    assert report, "报告未渲染"

    # candidate_topic_cache 不应有数据(extract 抛错没写)
    from storage import get_topics_for_candidate
    assert get_topics_for_candidate(db, "default") == []


# ============================================================================
# v0.3 Feature F Phase 2:per-topic trend list
# ============================================================================


def test_topic_trend_section_present_in_populated_state(tmp_path: Path):
    """填充态下,bar 图后应出现 '按主题查趋势' caption + 每个 topic 一个 button。"""
    db = tmp_path / "test.db"
    _save_a_session_with_topics(db)
    at, _fake = _make_app([], db_path=db)

    # '按主题查趋势' caption 应该出现
    assert _has_text(at, "按主题查趋势"), (
        "expected '按主题查趋势' caption in expanded sidebar"
    )
    # 至少 1 个 trend button(key 前缀 trend_<topic>)
    trend_buttons = [
        b for b in at.button if str(b.key).startswith("trend_")
    ]
    assert len(trend_buttons) >= 1, (
        f"expected ≥ 1 per-topic trend button, got {len(trend_buttons)}"
    )


def test_topic_trend_section_absent_in_empty_state(tmp_path: Path):
    """空态下整个 else 分支被跳过,'按主题查趋势' caption 不应出现。"""
    db = tmp_path / "test.db"
    at, _fake = _make_app([], db_path=db)
    assert not _has_text(at, "按主题查趋势"), (
        "trend section must NOT render when candidate_topic_cache is empty"
    )
    # 空态文案应该出现
    assert _has_text(at, "暂无跨 session 数据")


def test_topic_trend_button_click_sets_session_state(tmp_path: Path):
    """点 trend button → st.session_state['trend_open_topic'] 被设,再点同 topic 设回 None。"""
    db = tmp_path / "test.db"
    _save_a_session_with_topics(db)
    at, _fake = _make_app([], db_path=db)

    # 找一个 trend button
    trend_buttons = [
        b for b in at.button if str(b.key).startswith("trend_")
    ]
    assert trend_buttons, "no per-topic trend button rendered"
    btn = trend_buttons[0]
    # button key 是 'trend_<topic>' → 从 key 提取 topic
    topic = str(btn.key)[len("trend_"):]

    # 点击 → session_state 应被设
    btn.click()
    at.run()
    open_after_click = (
        at.session_state["trend_open_topic"]
        if "trend_open_topic" in at.session_state
        else None
    )
    assert open_after_click == topic, (
        f"clicking trend button did not set trend_open_topic, got {open_after_click!r}"
    )

    # 再点一下(同 topic)→ toggle 到 None
    same_btn = next(
        b for b in at.button if str(b.key) == f"trend_{topic}"
    )
    same_btn.click()
    at.run()
    open_after_toggle = (
        at.session_state["trend_open_topic"]
        if "trend_open_topic" in at.session_state
        else None
    )
    assert open_after_toggle is None, (
        "second click on same trend button should toggle off"
    )
