"""AI 面试官 (MVP) - Streamlit 单页应用。

启动:streamlit run app.py
"""
from __future__ import annotations

import streamlit as st

from config import get_llm_config
from llm import LLMError, chat
from prompts import (
    END_SIGNAL,
    LEVELS,
    STYLES,
    build_interviewer_system_prompt,
    build_report_prompt,
)
from resume_parser import ResumeParseError, parse_pdf_resume


# 测试 hook:monkeypatch app._do_chat 来替换 LLM。
# 注意 Streamlit 每次 rerun 都会重新执行本模块顶层代码,但 module-level 函数对象
# 在 import 时绑定,monkeypatch setattr 后不会跨 rerun 重置(它修改的是 app.__dict__)。
# 实际验证:monkeypatch 后 fake.calls 仍能记录到。
_chat_impl = chat


def _do_chat(messages, **kwargs):
    """调用 LLM。

    测试注入点:如果 st.session_state["mock_responses"] 存在,优先从该队列取响应;
    否则调真实 LLM。streamlit rerun 不会丢失 session_state,所以这是稳定的测试 hook。
    """
    mock_q = st.session_state.get("mock_responses")
    if isinstance(mock_q, list) and mock_q:
        return mock_q.pop(0)
    return _chat_impl(messages, **kwargs)


# ============================================================================
# 页面配置
# ============================================================================

st.set_page_config(
    page_title="AI 面试官 (MVP)",
    page_icon="🎯",
    layout="wide",
)

st.title("🎯 AI 面试官 · 简历 + JD + 6 档分级")
st.caption("给求职者用的面试实战模拟。基于个人简历 + 目标 JD + 职级定制,问完出复盘报告。")


# ============================================================================
# session_state 初始化
# ============================================================================

DEFAULTS = {
    "chat_history": [],
    "resume_content": "",
    "interview_level": LEVELS[3],  # 默认社招(中级)
    "interview_style": STYLES[0],  # 默认温和引导
    "jd_content": "",
    "interview_started": False,
    "interview_ended": False,
    "report_text": "",
    "error_msg": "",
    # 测试 hook:如果 setdefault 时已存在(mock_responses 不在 DEFAULTS 但 setdefault 不会创建),
    # 保留测试设置。Streamlit 每次 rerun 都会重新执行模块顶层,所以测试需要用
    # at.session_state[...] 显式注入(在 at.run() 之前或之后第一次 set_state)。
}
for k, v in DEFAULTS.items():
    st.session_state.setdefault(k, v)


# ============================================================================
# 侧边栏:简历 / 职级 / 风格
# ============================================================================

with st.sidebar:
    st.header("📋 面试配置")

    uploaded = st.file_uploader("上传简历 (PDF)", type=["pdf"])
    if uploaded is not None:
        try:
            text = parse_pdf_resume(uploaded.read())
            if text and text != st.session_state.resume_content:
                st.session_state.resume_content = text
                st.success(f"✅ 简历解析完成 ({len(text)} 字)")
        except ResumeParseError as e:
            st.error(f"❌ 简历解析失败:{e}")
            st.session_state.resume_content = ""

    st.session_state.interview_level = st.selectbox(
        "面试等级",
        LEVELS,
        index=LEVELS.index(st.session_state.interview_level),
        disabled=st.session_state.interview_started,
    )
    st.session_state.interview_style = st.radio(
        "面试风格",
        STYLES,
        index=STYLES.index(st.session_state.interview_style),
        disabled=st.session_state.interview_started,
    )

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

    st.divider()
    cfg = get_llm_config()
    if cfg.is_configured():
        st.caption(f"🤖 模型:{cfg.model}")
    else:
        st.warning("⚠️ 未配置 LLM_API_KEY,无法调用 LLM")


# ============================================================================
# 主区:JD 粘贴
# ============================================================================

st.subheader("🎯 目标岗位 JD")
st.session_state.jd_content = st.text_area(
    "粘贴岗位 JD(职责 / 任职要求 / 技术栈)",
    value=st.session_state.jd_content,
    height=160,
    placeholder="例:负责后端服务开发,熟悉 Python/Go,有高并发/微服务经验优先...",
)


# ============================================================================
# 工具函数
# ============================================================================

def _system_prompt() -> str:
    return build_interviewer_system_prompt(
        level=st.session_state.interview_level,
        style=st.session_state.interview_style,
        resume=st.session_state.resume_content,
        jd=st.session_state.jd_content,
    )


def _start_interview() -> None:
    """点击『开始面试』:清空历史 + 生成第一题。"""
    if not st.session_state.jd_content.strip():
        st.session_state.error_msg = "请先粘贴 JD 再开始面试"
        return
    st.session_state.chat_history = []
    st.session_state.interview_started = True
    st.session_state.interview_ended = False
    st.session_state.report_text = ""
    st.session_state.error_msg = ""

    messages = [
        {"role": "system", "content": _system_prompt()},
        {"role": "user", "content": "请开始面试"},
    ]
    try:
        first_q = _do_chat(messages)
    except LLMError as e:
        st.session_state.error_msg = str(e)
        st.session_state.interview_started = False
        return
    st.session_state.chat_history.append({"role": "assistant", "content": first_q})


def _handle_user_answer(answer: str) -> None:
    """用户提交回答:追加到 history + 生成下一题。"""
    st.session_state.chat_history.append({"role": "user", "content": answer})
    messages = [{"role": "system", "content": _system_prompt()}] + list(
        st.session_state.chat_history
    )
    try:
        next_q = _do_chat(messages)
    except LLMError as e:
        st.session_state.error_msg = str(e)
        return
    st.session_state.chat_history.append({"role": "assistant", "content": next_q})


def _generate_report() -> None:
    """结束面试,生成六维复盘报告。"""
    if not st.session_state.chat_history:
        st.session_state.error_msg = "还没有面试对话,无法生成报告"
        return
    prompt = build_report_prompt(
        level=st.session_state.interview_level,
        resume=st.session_state.resume_content,
        jd=st.session_state.jd_content,
        chat_history=list(st.session_state.chat_history),
    )
    try:
        report = _do_chat([{"role": "user", "content": prompt}], temperature=0.4)
    except LLMError as e:
        st.session_state.error_msg = str(e)
        return
    st.session_state.report_text = report
    st.session_state.interview_ended = True


# ============================================================================
# 控制条
# ============================================================================

st.divider()
ctrl_l, ctrl_m, ctrl_r = st.columns([1, 1, 2])

with ctrl_l:
    start_disabled = st.session_state.interview_started and not st.session_state.interview_ended
    if st.button(
        "🚀 开始面试" if not st.session_state.interview_started else "🔄 重新开始",
        type="primary",
        disabled=start_disabled,
        use_container_width=True,
    ):
        _start_interview()
        st.rerun()

with ctrl_m:
    end_disabled = not st.session_state.interview_started or st.session_state.interview_ended
    if st.button(
        "🛑 结束面试并出报告",
        type="secondary",
        disabled=end_disabled,
        use_container_width=True,
    ):
        _generate_report()
        st.rerun()

with ctrl_r:
    if st.session_state.interview_started:
        st.caption(
            f"状态:进行中 · {len(st.session_state.chat_history)} 条消息 · "
            f"{st.session_state.interview_level} · {st.session_state.interview_style}"
        )
    else:
        st.caption("状态:未开始")


# ============================================================================
# 错误提示
# ============================================================================

if st.session_state.error_msg:
    st.error(st.session_state.error_msg)
    if st.button("清除错误", key="clear_err"):
        st.session_state.error_msg = ""
        st.rerun()


# ============================================================================
# 聊天区
# ============================================================================

st.divider()
st.subheader("💬 面试对话")

if not st.session_state.chat_history:
    st.info("👈 配置好简历 / JD / 等级后,点『开始面试』即可。")
else:
    for msg in st.session_state.chat_history:
        if msg["role"] == "assistant":
            with st.chat_message("assistant", avatar="👨‍🏫"):
                st.markdown(msg["content"])
        else:
            with st.chat_message("user", avatar="🙋"):
                st.markdown(msg["content"])


# ============================================================================
# 用户输入(仅进行中可输入)
# ============================================================================

if st.session_state.interview_started and not st.session_state.interview_ended:
    user_input = st.chat_input("输入你的回答 (含『结束面试』可提前结束)")
    if user_input:
        _handle_user_answer(user_input)
        if END_SIGNAL in user_input:
            _generate_report()
        st.rerun()


# ============================================================================
# 报告区
# ============================================================================

if st.session_state.report_text:
    st.divider()
    st.subheader("📑 面试复盘报告")
    st.markdown(st.session_state.report_text)
    st.download_button(
        "💾 下载报告 (Markdown)",
        data=st.session_state.report_text,
        file_name="interview_report.md",
        mime="text/markdown",
    )
