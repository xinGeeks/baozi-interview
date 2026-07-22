"""AI 面试官 (MVP) - Streamlit 单页应用。

启动:streamlit run app.py
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

import streamlit as st

from config import get_llm_config
from feedback import build_feedback_prompt, parse_feedback_response
from llm import LLMError, chat, chat_stream
from prompts import (
    END_SIGNAL,
    LEVELS,
    STYLES,
    build_interviewer_system_prompt,
    build_report_prompt,
)
from resume_parser import ResumeParseError, parse_pdf_resume
from storage import (
    candidate_id_from_resume,
    get_session,
    init_db,
    list_sessions,
    save_session,
)


THINK_RE = re.compile(r"<think>(.*?)</think>", re.DOTALL)


def _split_think_blocks(content: str) -> tuple[list[str], str]:
    """把 <think>...</think> 块从 LLM 输出中拆出来。

    Returns:
        (think_blocks, visible_content): 块列表 + 移除 think 后的可见内容(已 strip)
    """
    thinks = THINK_RE.findall(content)
    visible = THINK_RE.sub("", content).strip()
    return thinks, visible


# 测试 hook:monkeypatch app._do_chat 来替换 LLM。
# 注意 Streamlit 每次 rerun 都会重新执行本模块顶层代码,但 module-level 函数对象
# 在 import 时绑定,monkeypatch setattr 后不会跨 rerun 重置(它修改的是 app.__dict__)。
# 实际验证:monkeypatch 后 fake.calls 仍能记录到。
_chat_impl = chat
_chat_stream_impl = chat_stream


def _do_chat(messages, *, temperature=0.7, purpose="chat", stream=False):
    """调用 LLM。

    测试注入点:
    - purpose="chat"(默认):如果 st.session_state["mock_responses"] 存在,
      优先从该队列取响应。
    - purpose="feedback":如果 st.session_state["mock_feedback_responses"] 存在,
      优先从该队列取响应。
    streamlit rerun 不会丢失 session_state,所以这是稳定的测试 hook。

    stream=True(purpose="chat" 时有效):
    返回 Iterator[str],供 st.write_stream 增量渲染。feedback 强制非流式
    (需要完整响应 parse)。mock 队列下用 iter([text]) 单块模拟。
    """
    if purpose == "feedback":
        mock_q = st.session_state.get("mock_feedback_responses")
        stream = False  # 反馈必须等完整
    else:
        mock_q = st.session_state.get("mock_responses")
    if isinstance(mock_q, list) and mock_q:
        text = mock_q.pop(0)
        if stream:
            return iter([text])
        return text
    if stream and purpose == "chat":
        return _chat_stream_impl(messages, temperature=temperature)
    return _chat_impl(messages, temperature=temperature)


# ============================================================================
# 页面配置
# ============================================================================

st.set_page_config(
    page_title="AI 面试官 (MVP)",
    page_icon="🎯",
    layout="wide",
)

# 数据库初始化(幂等 + mkdir);失败不阻断 UI(主流程不依赖 DB)
try:
    init_db()
except Exception as _e:
    st.warning(f"⚠️ 历史数据库初始化失败:{_e}")

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
    "turn_feedback": [],  # 每答一题追加一次:[{"question", "score", "advice"}, ...]
    # v0.3 Feature B: 持久化相关
    "current_session_id": "",       # 当前 session_id(报告生成时填)
    "loaded_session_id": "",        # 历史加载模式:加载的 session_id
    "interview_started_at": None,   # datetime 对象,_start_interview 时记
    "viewing_history": False,       # True 时主区显示历史 session 只读视图
    "success_msg": "",              # 一次性提示(如"已保存到历史")
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
                st.info("💾 面试对话将保存在本地 SQLite(不含简历原文)")
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

    # 历史面试区(v0.3 Feature B)
    st.divider()
    st.caption("📚 历史面试")
    try:
        cid = candidate_id_from_resume(st.session_state.resume_content)
        history = list_sessions(None, cid, limit=5)
    except Exception:
        history = []

    if not history:
        st.caption("（暂无历史）")
    else:
        for h in history:
            score_str = (
                f" · 均分 {h['score_avg']:.1f}"
                if h.get("score_avg") is not None
                else ""
            )
            label = (
                f"{h['ended_at'][:10]} · {h['level']} · "
                f"{h['turn_count']} 轮{score_str}"
            )
            if st.button(
                label, key=f"hist_{h['id']}", use_container_width=True
            ):
                st.session_state.loaded_session_id = h["id"]
                st.session_state.viewing_history = True
                st.rerun()


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
    """点击『开始面试』:清空历史 + 流式生成第一题。"""
    if not st.session_state.jd_content.strip():
        st.session_state.error_msg = "请先粘贴 JD 再开始面试"
        return
    st.session_state.chat_history = []
    st.session_state.turn_feedback = []
    st.session_state.interview_started = True
    st.session_state.interview_ended = False
    st.session_state.report_text = ""
    st.session_state.error_msg = ""
    st.session_state.success_msg = ""
    st.session_state.interview_started_at = datetime.now(timezone.utc)
    st.session_state.current_session_id = ""
    st.session_state.viewing_history = False

    messages = [
        {"role": "system", "content": _system_prompt()},
        {"role": "user", "content": "请开始面试"},
    ]
    pieces: list[str] = []
    try:
        with st.chat_message("assistant", avatar="👨‍🏫"):
            def _first_gen():
                for chunk in _do_chat(messages, stream=True):
                    pieces.append(chunk)
                    yield chunk
            st.write_stream(_first_gen)
    except LLMError as e:
        st.session_state.error_msg = str(e)
        st.session_state.interview_started = False
        return
    first_q = "".join(pieces)
    st.session_state.chat_history.append({"role": "assistant", "content": first_q})


def _handle_user_answer(answer: str) -> None:
    """用户提交回答:追加到 history → 逐轮反馈 → 流式生成下一题。"""
    st.session_state.chat_history.append({"role": "user", "content": answer})

    last_question = ""
    for msg in reversed(st.session_state.chat_history):
        if msg["role"] == "assistant":
            last_question = msg["content"]
            break

    # 逐轮反馈(反馈 LLM 不流式,继续用 _do_chat 不带 stream)
    try:
        feedback_messages = [{
            "role": "user",
            "content": build_feedback_prompt(
                level=st.session_state.interview_level,
                question=last_question,
                answer=answer,
            ),
        }]
        feedback_raw = _do_chat(
            feedback_messages, temperature=0.3, purpose="feedback"
        )
        parsed = parse_feedback_response(feedback_raw)
        st.session_state.turn_feedback.append({
            "question": last_question[:60],
            "score": parsed["score"],
            "advice": parsed["advice"],
        })
    except LLMError:
        st.session_state.turn_feedback.append({
            "question": last_question[:60],
            "score": -1,
            "advice": "",
        })

    messages = [{"role": "system", "content": _system_prompt()}] + list(
        st.session_state.chat_history
    )
    pieces: list[str] = []
    try:
        with st.chat_message("assistant", avatar="👨‍🏫"):
            def _next_gen():
                for chunk in _do_chat(messages, stream=True):
                    pieces.append(chunk)
                    yield chunk
            st.write_stream(_next_gen)
    except LLMError as e:
        st.session_state.error_msg = str(e)
        return
    next_q = "".join(pieces)
    st.session_state.chat_history.append({"role": "assistant", "content": next_q})


def _render_feedback_card(fb: dict) -> None:
    """渲染反馈小卡:📊 N/10 — advice(浅灰底,单行)。"""
    advice = (fb.get("advice") or "").replace("<", "&lt;").replace(">", "&gt;")
    st.markdown(
        f"<div style='background:#f0f2f6;padding:6px 10px;border-radius:6px;"
        f"font-size:0.85em;color:#333'>📊 <b>{fb['score']}/10</b> — {advice}</div>",
        unsafe_allow_html=True,
    )


def _render_history_view(session_id: str) -> None:
    """只读渲染历史 session(对话 + 报告)。"""
    try:
        sess = get_session(None, session_id)
    except Exception as e:
        st.error(f"加载历史失败:{e}")
        return

    if sess is None:
        st.warning(f"未找到历史会话 {session_id}")
        return

    score_str = (
        f" · 均分 {sess['score_avg']:.1f}"
        if sess.get("score_avg") is not None
        else ""
    )
    st.caption(
        f"📂 历史会话 · {sess['id']} · {sess['level']} · "
        f"{sess['style']} · {sess['ended_at'][:19]}{score_str}"
    )
    if st.button("← 返回新面试", key="back_from_history"):
        st.session_state.viewing_history = False
        st.session_state.loaded_session_id = ""
        st.rerun()

    st.subheader("💬 历史对话")
    feedback_by_idx = {f.get("turn_idx", i): f for i, f in enumerate(sess.get("feedback", []))}
    for i, msg in enumerate(sess["turns"]):
        if msg["role"] == "assistant":
            with st.chat_message("assistant", avatar="👨‍🏫"):
                st.markdown(msg["content"])
        else:
            with st.chat_message("user", avatar="🙋"):
                st.markdown(msg["content"])
            fb = feedback_by_idx.get(i // 2)
            if fb and fb.get("score", -1) >= 0:
                _render_feedback_card(fb)

    if sess.get("report_text"):
        st.divider()
        st.subheader("📑 复盘报告")
        st.markdown(sess["report_text"])
        st.download_button(
            "💾 下载报告 (Markdown)",
            data=sess["report_text"],
            file_name=f"interview_report_{sess['id']}.md",
            mime="text/markdown",
            key=f"dl_{sess['id']}",
        )


def _generate_report() -> None:
    """结束面试,生成六维复盘报告,并自动落盘到历史。"""
    if not st.session_state.chat_history:
        st.session_state.error_msg = "还没有面试对话,无法生成报告"
        return
    prompt = build_report_prompt(
        level=st.session_state.interview_level,
        resume=st.session_state.resume_content,
        jd=st.session_state.jd_content,
        chat_history=list(st.session_state.chat_history),
        turn_feedback=list(st.session_state.turn_feedback),
    )
    try:
        report = _do_chat([{"role": "user", "content": prompt}], temperature=0.4)
    except LLMError as e:
        st.session_state.error_msg = str(e)
        return
    st.session_state.report_text = report
    st.session_state.interview_ended = True

    # 落盘(失败不阻断 UI,但记 error_msg;报告仍可读可下载)
    try:
        sid = save_session(
            db_path=None,  # 让 storage 内部从 env 读最新路径(测试隔离用)
            level=st.session_state.interview_level,
            style=st.session_state.interview_style,
            jd=st.session_state.jd_content,
            resume_text=st.session_state.resume_content,
            chat_history=list(st.session_state.chat_history),
            turn_feedback=list(st.session_state.turn_feedback),
            report_text=report,
            started_at=(
                st.session_state.interview_started_at
                or datetime.now(timezone.utc)
            ),
        )
        st.session_state.current_session_id = sid
        st.session_state.success_msg = f"💾 已保存到历史 (id: {sid})"
    except Exception as e:
        st.session_state.error_msg = f"报告已生成,但保存到历史失败:{e}"


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

if st.session_state.success_msg:
    st.success(st.session_state.success_msg)
    st.session_state.success_msg = ""


# ============================================================================
# 聊天区
# ============================================================================

st.divider()
st.subheader("💬 面试对话")

if st.session_state.viewing_history and st.session_state.loaded_session_id:
    _render_history_view(st.session_state.loaded_session_id)
elif not st.session_state.chat_history:
    st.info("👈 配置好简历 / JD / 等级后,点『开始面试』即可。")
else:
    user_msg_seen = 0
    for idx, msg in enumerate(st.session_state.chat_history):
        if msg["role"] == "assistant":
            with st.chat_message("assistant", avatar="👨‍🏫"):
                thinks, visible = _split_think_blocks(msg["content"])
                if thinks:
                    with st.expander(
                        f"🧠 思考过程 ({len(thinks)} 块)", expanded=False
                    ):
                        for i, t in enumerate(thinks, 1):
                            if len(thinks) > 1:
                                st.markdown(f"**块 {i}**\n\n{t.strip()}")
                            else:
                                st.markdown(t.strip())
                if visible:
                    st.markdown(visible)
        else:
            with st.chat_message("user", avatar="🙋"):
                st.markdown(msg["content"])
            # 反馈卡(单行小卡;score=-1 表示本轮无反馈,不渲染)
            if user_msg_seen < len(st.session_state.turn_feedback):
                fb = st.session_state.turn_feedback[user_msg_seen]
                if fb.get("score", -1) >= 0:
                    _render_feedback_card(fb)
            user_msg_seen += 1


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
