"""专项练习页:围绕单个焦点主题深挖,不需要 JD。

与『配置』页并列的独立入口。填主题 → 置 practice_mode + pending_start →
跳到面试页(auto-start 生成围绕该主题的第一题)。
"""
from __future__ import annotations

import streamlit as st

from interview_helpers import (
    LEVELS,
    STYLES,
    _consume_nav,
    _token_counter,
    get_llm_config,
    request_nav,
    init_session_state,
)

init_session_state()
_consume_nav()  # 若有 pending_goto,在任何 widget 前跳走
st.session_state.current_page = "practice"

st.title("🎯 专项练习")
st.caption(
    "围绕一个具体主题深挖,不需要 JD、不需要简历。"
    "例:kafka 高可用、Redis 缓存击穿、系统设计能力。"
    "面试官首题直接切入主题,不做自我介绍开场。"
)

# ---- 焦点主题 ----
st.subheader("🔍 焦点主题")
practice_topic_input = st.text_input(
    "焦点主题",
    key="practice_topic_input",
    placeholder="输入要练习的主题,例:kafka 高可用",
    label_visibility="collapsed",
)

# ---- 等级 / 风格(复用全局 session_state,与配置页同源)----
st.subheader("⚙️ 练习参数")
col_l, col_s = st.columns(2)
with col_l:
    st.selectbox("难度等级", LEVELS, key="interview_level")
with col_s:
    st.radio("追问风格", STYLES, key="interview_style")

if st.session_state.resume_content:
    st.caption(
        f"📄 已上传简历 ({len(st.session_state.resume_content)} 字):"
        "会顺手做主题与项目经历的交叉验证(非必需)"
    )
else:
    st.caption("📄 无需简历、无需 JD:只围绕焦点主题提问")

# ---- LLM 配置 / 预算 ----
st.divider()
cfg = get_llm_config()
if cfg.is_configured():
    st.caption(f"🤖 模型:{cfg.model}")
else:
    st.warning("⚠️ 未配置 LLM_API_KEY,无法调用 LLM")

_tc = _token_counter()
if _tc.cap > 0 and _tc.is_blocked:
    st.error(
        f"❌ 今日预算已用完 ({_tc.current:,} / {_tc.cap:,} tokens)。"
        "明日 UTC 0 点重置,或调高 .env 中 LLM_DAILY_TOKEN_CAP。"
    )

# ---- 启动 ----
st.divider()
if st.session_state.error_msg:
    st.error(st.session_state.error_msg)

if st.button(
    "🎯 启动专项练习",
    type="primary",
    use_container_width=True,
    disabled=not practice_topic_input.strip(),
):
    st.session_state.error_msg = ""
    st.session_state.viewing_history = False
    st.session_state.loaded_session_id = ""
    st.session_state.practice_mode = True
    st.session_state.practice_topic = practice_topic_input.strip()
    st.session_state.pending_start = True
    request_nav("interview")
