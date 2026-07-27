"""配置页:简历 / JD / 职级 / 风格 + 开始面试。

流程第 1 页。填好配置点『🚀 开始面试』→ 校验 JD → 置 pending_start →
跳到面试页(auto-start trigger 生成第一题)。
"""
from __future__ import annotations

import streamlit as st

from interview_helpers import (
    LEVELS,
    STYLES,
    _consume_nav,
    _render_resume_prompt,
    _token_counter,
    get_llm_config,
    request_nav,
    init_session_state,
)
from resume_parser import ResumeParseError, parse_pdf_resume

init_session_state()
_consume_nav()  # 若有 pending_goto,在任何 widget 前跳走
st.session_state.current_page = "config"

st.title("🎯 配置面试")
st.caption("基于个人简历 + 目标 JD + 职级定制。填好后点『开始面试』。")

# ---- 续答 banner:检测到草稿时优先提示(不 st.stop,用户仍可选择重新配置)----
_render_resume_prompt(target="interview")

# ---- 简历上传 ----
st.subheader("📄 简历")
uploaded = st.file_uploader(
    "上传简历 (PDF)",
    type=["pdf"],
    key="resume_uploader",
)
if uploaded is not None:
    try:
        text = parse_pdf_resume(uploaded.read())
        if text and text != st.session_state.resume_content:
            st.session_state.resume_content = text
            st.success(f"✅ 简历解析完成 ({len(text)} 字)")
    except ResumeParseError as e:
        st.error(f"❌ 简历解析失败:{e}")
        st.session_state.resume_content = ""

if st.session_state.resume_content:
    with st.expander(
        f"👀 简历提取预览 ({len(st.session_state.resume_content)} 字)",
        expanded=False,
    ):
        st.text_area(
            "简历内容",
            value=st.session_state.resume_content,
            height=300,
            disabled=True,
            label_visibility="collapsed",
        )
else:
    st.caption("📄 暂未上传简历")

# ---- 目标 JD ----
st.subheader("🎯 目标岗位 JD")
st.session_state.jd_content = st.text_area(
    "粘贴岗位 JD(职责 / 任职要求 / 技术栈)",
    value=st.session_state.jd_content,
    height=160,
    placeholder="例:负责后端服务开发,熟悉 Python/Go,有高并发/微服务经验优先...",
)

# ---- 等级 / 风格 ----
st.subheader("⚙️ 面试参数")
col_l, col_s = st.columns(2)
with col_l:
    st.selectbox(
        "面试等级",
        LEVELS,
        key="interview_level",
    )
with col_s:
    st.radio(
        "面试风格",
        STYLES,
        key="interview_style",
    )

# ---- LLM 配置 / 预算 ----
st.divider()
cfg = get_llm_config()
if cfg.is_configured():
    st.caption(f"🤖 模型:{cfg.model}")
else:
    st.warning("⚠️ 未配置 LLM_API_KEY,无法调用 LLM")

_tc = _token_counter()
if _tc.cap > 0:
    if _tc.is_blocked:
        st.error(
            f"❌ 今日预算已用完 ({_tc.current:,} / {_tc.cap:,} tokens)。"
            "明日 UTC 0 点重置,或调高 .env 中 LLM_DAILY_TOKEN_CAP。"
        )
    elif _tc.is_warning:
        st.warning(
            f"⚠️ 已用 {_tc.percent:.0%} 今日预算 "
            f"({_tc.current:,} / {_tc.cap:,} tokens,估算 ±25%)"
        )
    else:
        st.progress(
            min(_tc.percent, 1.0),
            text=f"今日预算:{_tc.current:,} / {_tc.cap:,} tokens",
        )

# ---- 开始面试 ----
st.divider()
if st.session_state.error_msg:
    st.error(st.session_state.error_msg)

if st.button("🚀 开始面试", type="primary", use_container_width=True):
    if not st.session_state.jd_content.strip():
        st.session_state.error_msg = "请先粘贴 JD 再开始面试"
        st.rerun()
    else:
        st.session_state.error_msg = ""
        st.session_state.viewing_history = False
        st.session_state.loaded_session_id = ""
        st.session_state.pending_start = True
        request_nav("interview")
