"""面试页:对话循环 + 逐轮反馈 + 输入框。

流程第 2 页。到达时若 pending_start 为真则 auto-start 生成第一题。
END_SIGNAL / 结束按钮 → 生成报告 → 跳报告页。
"""
from __future__ import annotations

import streamlit as st

from interview_helpers import (
    END_SIGNAL,
    _consume_nav,
    _generate_report,
    _handle_user_answer,
    _render_feedback_card,
    _render_message_body,
    _render_resume_prompt,
    _start_interview,
    _token_counter,
    goto,
    request_nav,
    init_session_state,
)

init_session_state()
_consume_nav()
st.session_state.current_page = "interview"

# ---- 报告已生成 → 跳报告页(在任何 widget 创建前 navigate,避免 AppTest
# 在同一 run 内 switch_page 时 chat_input widget state 悬空报 KeyError)----
if st.session_state.get("pending_report_nav"):
    st.session_state.pending_report_nav = False
    goto("report")

# ---- auto-start:从配置页带 pending_start 进来 ----
if (
    st.session_state.get("pending_start")
    and not st.session_state.interview_started
    and not st.session_state.interview_ended
    and not st.session_state.viewing_history
):
    st.session_state.pending_start = False
    _start_interview()
    # 重跑一次:丢弃 auto-start 内联流式渲染,统一由下方 history 循环渲染
    st.rerun()

_is_practice = bool(st.session_state.get("practice_mode"))
if _is_practice:
    st.title("🎯 专项练习")
    st.caption(
        f"焦点主题:{st.session_state.practice_topic} · "
        f"{st.session_state.interview_level} · "
        f"{st.session_state.interview_style}"
    )
else:
    st.title("💬 面试对话")
    st.caption(
        f"{st.session_state.interview_level} · {st.session_state.interview_style}"
    )

# ---- 错误 / 成功提示 ----
if st.session_state.error_msg:
    st.error(st.session_state.error_msg)
    if st.button("清除错误", key="clear_err"):
        st.session_state.error_msg = ""
        st.rerun()
if st.session_state.success_msg:
    st.success(st.session_state.success_msg)
    st.session_state.success_msg = ""

# ---- 未开始:引导回配置页(若有草稿,先出续答 banner)----
if not st.session_state.interview_started:
    if _render_resume_prompt(target="interview"):
        st.stop()
    st.info(
        "👈 还没开始。请到『配置』页填好简历 / JD 后点『开始面试』,"
        "或输入主题启动『专项练习』。"
    )
    if st.button("← 去配置页", key="goto_config_from_interview"):
        request_nav("config")
    st.stop()

# ---- 对话渲染 ----
user_msg_seen = 0
for msg in st.session_state.chat_history:
    if msg["role"] == "assistant":
        with st.chat_message("assistant", avatar="👨‍🏫"):
            _render_message_body(msg["content"])
    else:
        with st.chat_message("user", avatar="🙋"):
            st.markdown(msg["content"])
        if user_msg_seen < len(st.session_state.turn_feedback):
            fb = st.session_state.turn_feedback[user_msg_seen]
            if fb.get("score", -1) >= 0:
                flags = (
                    st.session_state.turn_authenticity_flags[user_msg_seen]
                    if user_msg_seen < len(st.session_state.turn_authenticity_flags)
                    else []
                )
                _render_feedback_card(fb, authenticity_flags=flags)
        user_msg_seen += 1

# ---- 控制:结束面试 ----
st.divider()
if not st.session_state.interview_ended:
    _end_label = (
        "🚪 退出专项练习并出报告" if _is_practice else "🛑 结束面试并出报告"
    )
    if st.button(_end_label, key="end_interview", type="secondary"):
        _generate_report()
        st.session_state.pending_report_nav = True
        st.rerun()

# ---- 输入框(仅进行中) ----
if st.session_state.interview_started and not st.session_state.interview_ended:
    _budget_blocked = _token_counter().is_blocked
    if _budget_blocked:
        st.warning(
            "⛔ 今日 token 预算已用完,无法继续面试。"
            "可结束面试并生成报告,或等到 UTC 0 点重置。"
        )
    _placeholder = (
        "输入你的回答 (含『结束面试』可提前退出练习)"
        if _is_practice
        else "输入你的回答 (含『结束面试』可提前结束)"
    )
    user_input = st.chat_input(_placeholder, disabled=_budget_blocked)
    if user_input and not _budget_blocked:
        should_end = END_SIGNAL in user_input
        _handle_user_answer(user_input, generate_next=not should_end)
        if END_SIGNAL in user_input:
            _generate_report()
            st.session_state.pending_report_nav = True
        st.rerun()
