"""AI 面试官 (MVP) - Streamlit 单页应用。

启动:streamlit run app.py
"""
from __future__ import annotations

import re
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

from config import get_daily_token_cap, get_llm_config, get_retention_days
from cost import DailyTokenCounter, estimate_messages_tokens, estimate_tokens
from feedback import build_feedback_prompt, parse_feedback_response
from llm import (
    AuthError,
    LLMError,
    RateLimitError_,
    TransientError,
    UnknownError,
    chat,
    chat_stream,
)
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
    clear_all_sessions_for_candidate,
    delete_session,
    get_session,
    has_accepted_tos,
    init_db,
    list_sessions,
    purge_expired_sessions,
    record_consent,
    save_session,
)
from authenticity import (
    AuthenticityReport,
    build_authenticity_judgment_prompt,
    detect_signals,
    parse_authenticity_response,
)


THINK_RE = re.compile(r"<think>(.*?)</think>", re.DOTALL)


# v0.3 alpha-kickoff: ToS 版本号。修改 ToS 内容时需 bump,会触发重新接受。
TOS_VERSION = "2026-07-22-v1"

# 复用文本(UI 通知 + file_uploader help + ToS modal 摘要)
PII_NOTICE = (
    "📌 简历原文**不持久化**,仅用于本场面试上下文;对话记录保存在本地 SQLite,"
    "可在历史区删除。详见侧边栏底部与 [docs/privacy.md](docs/privacy.md)。"
)
PII_NOTICE_PLAIN = (
    "简历原文不持久化,仅用于本场面试上下文;对话记录保存在本地 SQLite,"
    "可在历史区删除。"
)
TOS_SUMMARY = (
    "本工具:\n"
    "- 不存简历原文,只存对话 + 报告\n"
    "- 不向任何第三方分享数据(LLM 调用除外)\n"
    "- 30 天后自动清理历史(可配 STORAGE_RETENTION_DAYS)\n"
    "- 你随时可在历史区单条删除 / 一键清空\n\n"
    "本工具**不构成录用判断**,仅作求职者自查参考。"
)


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

    v0.3 alpha-kickoff: 每次调用前先估算 input tokens 累加;流式下收尾时
    再累加 output 估算。预算超限时仍允许调用(仅 UI 警告 / 禁用输入框),
    不阻断 LLM 调用本身(避免半路崩掉用户体验)。
    """
    # 估算并累加 input tokens(进入前)
    _token_counter().add(estimate_messages_tokens(messages))

    if purpose == "feedback":
        mock_q = st.session_state.get("mock_feedback_responses")
        stream = False  # 反馈必须等完整
    else:
        mock_q = st.session_state.get("mock_responses")
    if isinstance(mock_q, list) and mock_q:
        text = mock_q.pop(0)
        if stream:
            return _TrackingStream(iter([text]))
        _token_counter().add(estimate_tokens(text))  # 累加 mock output
        return text
    if stream and purpose == "chat":
        return _TrackingStream(_chat_stream_impl(messages, temperature=temperature))
    result = _chat_impl(messages, temperature=temperature)
    _token_counter().add(estimate_tokens(result))
    return result


class _TrackingStream:
    """包装 stream iterator,累加 output token 数(在迭代结束时)。

    不修改 yield 行为,只顺手累加成本。
    """
    def __init__(self, inner):
        self._inner = inner
        self._buffer: list[str] = []

    def __iter__(self):
        return self

    def __next__(self):
        chunk = next(self._inner)
        self._buffer.append(chunk)
        return chunk

    def close(self):
        # 迭代结束 / GC 时累加 output
        if self._buffer:
            _token_counter().add(estimate_tokens("".join(self._buffer)))
            self._buffer = []


def _token_counter() -> DailyTokenCounter:
    """懒初始化 token 计数器(确保 cap 与 env 同步)。"""
    if st.session_state.token_counter is None:
        st.session_state.token_counter = DailyTokenCounter(cap=get_daily_token_cap())
    else:
        # cap 可能因 .env 改动而变;每次访问同步
        st.session_state.token_counter.cap = get_daily_token_cap()
    return st.session_state.token_counter


# ============================================================================
# 全局异常处理(v0.3 alpha-kickoff)
# 注册 sys.excepthook → 未捕获异常写 data/error.log + 不让页面整块挂掉
# ============================================================================

_ERROR_LOG_PATH = Path(__file__).parent / "data" / "error.log"


def _install_global_error_handler() -> None:
    """注册 sys.excepthook,记录未捕获异常。只记 type + 截断 200 字,不记 resume。"""
    def _hook(exc_type, exc_value, exc_tb):
        # 过滤 KeyboardInterrupt / SystemExit(用户主动终止,非 bug)
        if issubclass(exc_type, (KeyboardInterrupt, SystemExit)):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        try:
            _ERROR_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            tb_text = "".join(
                traceback.format_exception(exc_type, exc_value, exc_tb)
            )[:500]
            with _ERROR_LOG_PATH.open("a", encoding="utf-8") as f:
                f.write(
                    f"[{datetime.now(timezone.utc).isoformat()}] "
                    f"{exc_type.__name__}: {str(exc_value)[:200]}\n{tb_text}\n"
                    f"{'-' * 60}\n"
                )
        except Exception:
            pass  # 兜底:error.log 写失败也不抛
        # 不调 sys.__excepthook__,避免打印到 stderr 把终端刷爆
    sys.excepthook = _hook


_install_global_error_handler()


# ============================================================================
# 错误友好提示(v0.3 alpha-kickoff)
# ============================================================================


def _user_friendly_error(e: LLMError) -> str:
    """把 LLMError 子类翻译成用户可读的中文提示。"""
    if isinstance(e, AuthError):
        return "🔑 API key 无效或权限不足。请检查 .env 中的 LLM_API_KEY,或登录平台控制台确认账户状态。"
    if isinstance(e, RateLimitError_):
        return "⏱️ 请求过快或触发限流。请稍候 30 秒后重试;或考虑切到更便宜的模型。"
    if isinstance(e, TransientError):
        return "🌐 网络不稳定或服务暂时不可达。请检查网络后重试;若持续失败请反馈。"
    if isinstance(e, UnknownError):
        return f"❓ 未知错误:{str(e)[:200]}。详情见 data/error.log。"
    return f"❌ LLM 调用失败:{str(e)[:200]}"


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
    # v0.3 alpha-kickoff: lazy 清理过期 session(retention_days=0 时不删)
    _retention = get_retention_days()
    if _retention > 0:
        purge_expired_sessions(None, _retention)
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
    # v0.3 Feature E: 真实性检测
    "turn_authenticity_flags": [],  # 每答一题追加一次:list[str],per-turn 启发式信号
    "authenticity_report": None,    # AuthenticityReport 或 None(报告末尾 LLM 聚合结果)
    # v0.3 alpha-kickoff: ToS / 成本 / 删除
    "tos_accepted": False,          # 当前 candidate_id + TOS_VERSION 是否接受
    "tos_check_done": False,        # 是否已查过 DB(避免每次 rerun 都查)
    "token_counter": None,          # DailyTokenCounter(懒初始化,见 _token_counter)
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
    st.caption(PII_NOTICE_PLAIN)

    uploaded = st.file_uploader(
        "上传简历 (PDF)",
        type=["pdf"],
        help=PII_NOTICE_PLAIN,
    )
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

    # 预算条(v0.3 alpha-kickoff)
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
            col_a, col_b = st.columns([4, 1])
            with col_a:
                if st.button(
                    label, key=f"hist_{h['id']}", use_container_width=True
                ):
                    st.session_state.loaded_session_id = h["id"]
                    st.session_state.viewing_history = True
                    st.rerun()
            with col_b:
                # 单条删除(二次确认通过 popover)
                with st.popover("🗑️"):
                    st.caption(
                        f"将永久删除 {h['ended_at'][:10]} 的 {h['turn_count']} 轮面试。"
                    )
                    if st.button(
                        "确认删除",
                        key=f"del_{h['id']}",
                        type="secondary",
                        use_container_width=True,
                    ):
                        try:
                            delete_session(None, h["id"])
                            st.session_state.success_msg = (
                                f"🗑️ 已删除 {h['ended_at'][:10]} 的面试"
                            )
                            st.rerun()
                        except Exception as e:
                            st.error(f"删除失败:{e}")

        # 批量清空按钮(强制输入"确认删除")
        with st.expander("⚠️ 清空我的全部历史", expanded=False):
            st.caption(
                f"将永久删除你的全部 {len(history)} 条历史 session。"
            )
            confirm_text = st.text_input(
                '输入"确认删除"以启用按钮',
                key="bulk_clear_confirm",
            )
            if st.button(
                "清空全部历史",
                key="bulk_clear_btn",
                type="secondary",
                disabled=(confirm_text.strip() != "确认删除"),
                use_container_width=True,
            ):
                try:
                    _cid = candidate_id_from_resume(
                        st.session_state.resume_content
                    )
                    n = clear_all_sessions_for_candidate(None, _cid)
                    st.session_state.success_msg = (
                        f"🗑️ 已清空 {n} 条历史 session"
                    )
                    st.rerun()
                except Exception as e:
                    st.error(f"清空失败:{e}")


# ============================================================================
# ToS 接受闸门(v0.3 alpha-kickoff)
# 未接受当前 TOS_VERSION → 强制 modal + 禁用开始面试
# ============================================================================

if not st.session_state.tos_check_done:
    try:
        _cid = candidate_id_from_resume(st.session_state.resume_content)
        st.session_state.tos_accepted = has_accepted_tos(None, _cid, TOS_VERSION)
    except Exception:
        st.session_state.tos_accepted = False
    st.session_state.tos_check_done = True

if not st.session_state.tos_accepted:
    st.subheader("📜 服务条款 (ToS)")
    with st.container(border=True):
        st.markdown(f"**版本**:`{TOS_VERSION}`")
        st.markdown(TOS_SUMMARY)
        with st.expander("完整隐私政策与 ToS", expanded=False):
            try:
                tos_text = (Path(__file__).parent / "docs" / "privacy.md").read_text(
                    encoding="utf-8"
                )
                st.markdown(tos_text)
            except Exception as e:
                st.warning(f"无法加载完整 ToS 文本:{e}")
        agreed = st.checkbox(
            f"我已阅读并同意 {TOS_VERSION} 版本的服务条款与隐私政策",
            key="tos_checkbox",
        )
        if st.button(
            "✅ 确认接受",
            type="primary",
            disabled=not agreed,
            use_container_width=True,
        ):
            try:
                _cid = candidate_id_from_resume(st.session_state.resume_content)
                record_consent(None, _cid, TOS_VERSION)
                st.session_state.tos_accepted = True
                st.success("✅ 已接受 ToS,现在可以开始面试")
                st.rerun()
            except Exception as e:
                st.error(f"记录接受状态失败:{e}")
    st.stop()


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
        st.session_state.error_msg = _user_friendly_error(e)
        st.session_state.interview_started = False
        return
    except Exception as e:
        st.session_state.error_msg = f"❌ 意外错误:{type(e).__name__}: {str(e)[:200]}"
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

    # v0.3 Feature E: per-turn 启发式真实性信号检测(零 LLM 成本,<1ms)
    flags = detect_signals(
        question=last_question,
        answer=answer,
        resume_text=st.session_state.resume_content,
    )
    st.session_state.turn_authenticity_flags.append(flags)

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
        st.session_state.error_msg = _user_friendly_error(e)
        return
    except Exception as e:
        st.session_state.error_msg = f"❌ 意外错误:{type(e).__name__}: {str(e)[:200]}"
        return
    next_q = "".join(pieces)
    st.session_state.chat_history.append({"role": "assistant", "content": next_q})


def _render_feedback_card(fb: dict, authenticity_flags: list[str] | None = None) -> None:
    """渲染反馈小卡:📊 N/10 — advice(浅灰底,单行)+ 可选 ⚠️ 真实性提示。

    authenticity_flags 非空时,追加一行 amber 底色的 flag 提示(最显眼的 1 个)。
    flag-only,不修改分数 — 候选人有最终判断权。
    """
    advice = (fb.get("advice") or "").replace("<", "&lt;").replace(">", "&gt;")
    warn_html = ""
    if authenticity_flags:
        top_flag = authenticity_flags[0]
        warn_html = (
            f"<div style='background:#fff3cd;padding:4px 8px;border-radius:4px;"
            f"font-size:0.8em;color:#856404;margin-top:4px'>"
            f"⚠️ 真实性提示:{top_flag}</div>"
        )
    st.markdown(
        f"<div style='background:#f0f2f6;padding:6px 10px;border-radius:6px;"
        f"font-size:0.85em;color:#333'>📊 <b>{fb['score']}/10</b> — {advice}</div>"
        f"{warn_html}",
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
        st.session_state.error_msg = _user_friendly_error(e)
        return
    except Exception as e:
        st.session_state.error_msg = f"❌ 报告生成意外错误:{type(e).__name__}: {str(e)[:200]}"
        return
    st.session_state.report_text = report
    st.session_state.interview_ended = True

    # v0.3 Feature E: 报告末尾追加真实性维度(单次 LLM 聚合;失败不阻断主报告)
    auth_report = _aggregate_authenticity()
    if auth_report is not None and auth_report.is_valid:
        st.session_state.authenticity_report = auth_report
        section_7 = _render_authenticity_section(auth_report)
        if section_7:
            st.session_state.report_text = report + "\n\n" + section_7

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
            report_text=st.session_state.report_text,
            started_at=(
                st.session_state.interview_started_at
                or datetime.now(timezone.utc)
            ),
        )
        st.session_state.current_session_id = sid
        st.session_state.success_msg = f"💾 已保存到历史 (id: {sid})"
    except Exception as e:
        st.session_state.error_msg = f"报告已生成,但保存到历史失败:{e}"


def _aggregate_authenticity() -> AuthenticityReport | None:
    """报告生成时调一次 LLM 聚合启发式 signals → AuthenticityReport。

    失败 → 返回 None(主报告照常出,UI 不显示真实性段)。
    """
    prompt = build_authenticity_judgment_prompt(
        resume=st.session_state.resume_content,
        jd=st.session_state.jd_content,
        chat_history=list(st.session_state.chat_history),
        turn_flags=list(st.session_state.turn_authenticity_flags),
    )
    try:
        raw = _do_chat([{"role": "user", "content": prompt}], temperature=0.3)
    except LLMError:
        return None
    return parse_authenticity_response(raw)


def _render_authenticity_section(report: AuthenticityReport) -> str:
    """生成报告「第 7 段 · 真实性维度」Markdown。失败/parse 错 → 空串(隐藏)。"""
    if not report.is_valid:
        return ""
    score_pct = int(round(report.score * 100))
    tone = "🟢" if score_pct >= 80 else ("🟡" if score_pct >= 60 else "🔴")
    findings_md = "\n".join(
        f"- **轮 {f.turn}** · {f.issue}:{f.detail}" for f in report.findings
    ) or "- (无关键发现)"
    summary = report.summary or "(无摘要)"
    return f"""### 7. 真实性维度 {tone} {score_pct} 分

**整体评估**:{summary}

**关键发现**:
{findings_md}

> 注:真实性检测仅作参考,不构成录用判断。分数 = 简历 / JD / 回答三方一致性的启发式 + LLM 综合评估。"""


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
                    flags = (
                        st.session_state.turn_authenticity_flags[user_msg_seen]
                        if user_msg_seen < len(
                            st.session_state.turn_authenticity_flags
                        )
                        else []
                    )
                    _render_feedback_card(fb, authenticity_flags=flags)
            user_msg_seen += 1


# ============================================================================
# 用户输入(仅进行中可输入)
# ============================================================================

if st.session_state.interview_started and not st.session_state.interview_ended:
    _budget_blocked = _token_counter().is_blocked
    if _budget_blocked:
        st.warning(
            "⛔ 今日 token 预算已用完,无法继续面试。"
            "可结束面试并生成报告,或等到 UTC 0 点重置。"
        )
    user_input = st.chat_input(
        "输入你的回答 (含『结束面试』可提前结束)",
        disabled=_budget_blocked,
    )
    if user_input and not _budget_blocked:
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
