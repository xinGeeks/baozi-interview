"""训练图谱页:跨会话主题图谱 + 弱 topic 专项练习 + 查看历史。

流程第 4 页。展示反复出现的主题(cloud + Top-10 bar + per-topic 趋势),
点候选主题 → 进入专项训练(复用面试页 chat loop)。
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from interview_helpers import (
    _consume_nav,
    _topic_cloud_html,
    backfill_topics_for_candidate,
    get_candidate_id,
    get_topic_trend,
    get_topics_for_candidate,
    request_nav,
    init_session_state,
    list_sessions,
)

init_session_state()
_consume_nav()
st.session_state.current_page = "topics"

st.title("🎯 训练图谱")
st.caption("看你反复练什么、反复弱什么;点主题可直接专项深挖。")

try:
    backfill_topics_for_candidate(None, get_candidate_id())
except Exception:
    pass

# ============================================================================
# 跨会话训练图谱
# ============================================================================
with st.expander("🎯 跨会话训练图谱", expanded=True):
    try:
        topics = get_topics_for_candidate(None, get_candidate_id())
    except Exception:
        topics = []
    if not topics:
        st.caption("暂无跨 session 数据,完成第 2 场后会自动出现。")
    else:
        st.markdown(
            "**训练主题云**(字号越大 = 反复出现且占比越高):",
            help="主题 = 多场面试反复提到的关键词汇,已脱敏处理。",
        )
        st.markdown(_topic_cloud_html(topics), unsafe_allow_html=True)
        st.divider()
        st.caption("**Top-10 主题得分**(基于训练频次归一化):")
        top10 = topics[:10]
        chart_df = pd.DataFrame(
            {
                "topic": [t.topic for t in top10],
                "score": [t.score for t in top10],
            }
        ).set_index("topic")
        try:
            st.bar_chart(data=chart_df, y="score", height=240)
        except Exception:
            st.bar_chart({"score": [t.score for t in top10]}, height=240)

        st.divider()
        st.caption("🔍 按主题查趋势(点击展开):")
        for t in topics:
            is_open = st.session_state.get("trend_open_topic") == t.topic
            btn_label = f"{'▼' if is_open else '▶'} {t.topic}"
            if st.button(btn_label, key=f"trend_{t.topic}", use_container_width=True):
                st.session_state["trend_open_topic"] = (
                    None if is_open else t.topic
                )
                st.rerun()
        trend_topic = st.session_state.get("trend_open_topic")
        if trend_topic:
            try:
                trend = get_topic_trend(None, get_candidate_id(), trend_topic)
            except Exception:
                trend = []
            if len(trend) < 2:
                st.caption(f"⚠️ 仅 {len(trend)} 场会话,需要 ≥ 2 场才能画趋势。")
            else:
                trend_chart_df = pd.DataFrame(
                    {"score": [round(s, 4) for _, s, _ in trend]},
                    index=[ended_at[:10] for _, _, ended_at in trend],
                ).rename_axis("session_date")
                try:
                    st.line_chart(trend_chart_df, y="score", height=200)
                except Exception:
                    st.line_chart([s for _, s, _ in trend], height=200)

# ============================================================================
# 弱 topic 专项练习
# ============================================================================
with st.expander("🎯 弱 topic 专项练习", expanded=True):
    st.caption(
        "高频主题 = 反复提到,优先练。"
        "分数 = 训练图谱中的提及占比,**不代表掌握度**。"
    )
    try:
        practice_topics = get_topics_for_candidate(None, get_candidate_id())[:8]
    except Exception:
        practice_topics = []
    if not practice_topics:
        st.caption(
            "📭 暂无候选主题。先完成 1-2 场面试,主题出现在"
            "『跨会话训练图谱』后再来。"
        )
    else:
        for t in practice_topics:
            if st.button(
                f"📍 {t.topic}",
                key=f"practice_entry_{t.topic}",
                use_container_width=True,
            ):
                st.session_state.practice_mode = True
                st.session_state.practice_topic = t.topic
                st.session_state.viewing_history = False
                st.session_state.loaded_session_id = ""
                st.session_state.pending_start = True
                request_nav("interview")

# ============================================================================
# 查看历史(跳报告页只读)
# ============================================================================
with st.expander("📚 查看历史", expanded=False):
    try:
        cid = get_candidate_id()
        history = list_sessions(None, cid, limit=10)
    except Exception:
        history = []
    if not history:
        st.caption("（暂无历史）")
    else:
        for h in history:
            mode_badge = "🎯 练习 · " if h.get("mode") == "practice" else ""
            label = (
                f"{mode_badge}{h['ended_at'][:10]} · {h['level']} · "
                f"{h['turn_count']} 轮"
            )
            if st.button(label, key=f"topics_hist_{h['id']}", use_container_width=True):
                st.session_state.loaded_session_id = h["id"]
                st.session_state.viewing_history = True
                request_nav("report")
