"""报告页:本场报告 / 历史报告 切换 + 下一场 跳转。

流程第 3 页。面试结束后落在这里。不自动跳走 —— 用户显式点『下一场』
离开。历史只读视图整合在『历史报告』段。
"""
from __future__ import annotations

import streamlit as st

from interview_helpers import (
    _consume_nav,
    _render_history_view,
    _render_message_body,
    delete_session,
    get_candidate_id,
    request_nav,
    init_session_state,
    list_sessions,
)

init_session_state()
_consume_nav()
st.session_state.current_page = "report"

st.title("📑 面试复盘报告")

_default_seg = (
    "历史报告"
    if (st.session_state.viewing_history and st.session_state.loaded_session_id)
    else "本场报告"
)
seg = st.segmented_control(
    "视图",
    ["本场报告", "历史报告"],
    default=_default_seg,
    key="report_view",
    label_visibility="collapsed",
)

if st.session_state.success_msg:
    st.success(st.session_state.success_msg)
    st.session_state.success_msg = ""

# ============================================================================
# 本场报告
# ============================================================================
if seg == "本场报告":
    if st.session_state.report_text:
        _render_message_body(st.session_state.report_text)
        st.download_button(
            "💾 下载报告 (Markdown)",
            data=st.session_state.report_text,
            file_name="interview_report.md",
            mime="text/markdown",
        )
        st.divider()
        if st.button(
            "➡️ 下一场",
            type="primary",
            use_container_width=True,
            key="report_next_session",
        ):
            # 重置本场状态,回配置页
            st.session_state.chat_history = []
            st.session_state.turn_feedback = []
            st.session_state.turn_authenticity_flags = []
            st.session_state.interview_started = False
            st.session_state.interview_ended = False
            st.session_state.report_text = ""
            st.session_state.authenticity_report = None
            st.session_state.current_session_id = ""
            st.session_state.loaded_session_id = ""
            st.session_state.viewing_history = False
            st.session_state.practice_mode = False
            st.session_state.practice_topic = ""
            request_nav("config")
    else:
        st.info("还没有本场报告。先到『配置』页开始一场面试。")
        if st.button("← 去配置页", key="goto_config_from_report"):
            request_nav("config")

# ============================================================================
# 历史报告(只读)
# ============================================================================
else:
    if st.session_state.viewing_history and st.session_state.loaded_session_id:
        if st.button("← 返回历史列表", key="back_to_history_list"):
            st.session_state.viewing_history = False
            st.session_state.loaded_session_id = ""
            st.rerun()
        _render_history_view(st.session_state.loaded_session_id)
    else:
        try:
            cid = get_candidate_id()
            history = list_sessions(None, cid, limit=20)
        except Exception:
            history = []
        if not history:
            st.caption("（暂无历史）")
        else:
            st.caption("点击查看某场历史(只读):")
            for h in history:
                score_str = (
                    f" · 均分 {h['score_avg']:.1f}"
                    if h.get("score_avg") is not None
                    else ""
                )
                mode_badge = (
                    "🎯 练习 · " if h.get("mode") == "practice" else ""
                )
                label = (
                    f"{mode_badge}{h['ended_at'][:10]} · {h['level']} · "
                    f"{h['turn_count']} 轮{score_str}"
                )
                col_view, col_del = st.columns([6, 1])
                with col_view:
                    if st.button(
                        label, key=f"hist_{h['id']}", use_container_width=True
                    ):
                        st.session_state.loaded_session_id = h["id"]
                        st.session_state.viewing_history = True
                        st.rerun()
                with col_del:
                    with st.popover("🗑️", use_container_width=True):
                        st.caption("确认删除这场?不可恢复。")
                        if st.button(
                            "确认删除", key=f"del_{h['id']}", type="primary"
                        ):
                            try:
                                delete_session(None, h["id"])
                                st.session_state.success_msg = "🗑️ 已删除该场历史"
                                st.rerun()
                            except Exception as e:
                                st.error(f"删除失败:{e}")
