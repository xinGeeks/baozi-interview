"""跨页共享逻辑(v0.3 multipage-navigation)。

app.py(entry)与 pages/*.py 都从这里 import 常量、session_state 初始化、
LLM 调用 hook、面试状态机与渲染 helper。

放在仓库根(而非 pages/)的原因:st.navigation 模式下 pages/ 目录不在 sys.path,
兄弟模块无法 import;根级模块可被 entry 先 import 进 sys.modules,pages 再 import
即命中缓存(与 storage / prompts 等既有模块同理)。
"""
from __future__ import annotations

import re
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

import prompts
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
from storage import (
    clear_all_sessions_for_candidate,
    clear_autosave,
    delete_session,
    get_candidate_id,
    get_session,
    init_db,
    list_sessions,
    load_autosave,
    purge_expired_sessions,
    save_autosave,
    save_session,
)  # noqa: F401 — re-exported for app.py / pages/*.py convenience
from authenticity import (
    AuthenticityReport,
    build_authenticity_judgment_prompt,
    detect_signals,
    parse_authenticity_response,
)


THINK_RE = re.compile(r"%(OPEN)s(.*?)%(CLOSE)s" % {"OPEN": "<think>", "CLOSE": "</think>"}, re.DOTALL)




_ERROR_LOG_PATH = Path(__file__).parent / "data" / "error.log"


# ============================================================================
# 跨页导航
# ============================================================================

PAGE_PATHS = {
    "config": "pages/config.py",
    "practice": "pages/practice.py",
    "interview": "pages/interview.py",
    "report": "pages/report.py",
}


def goto(page_key: str) -> None:
    """设置 current_page 标记并跳到目标页。

    先写 st.session_state.current_page(供测试断言 / sidebar 判断上下文),
    再调 st.switch_page。标记必须在 switch_page 前写,因为 AppTest 单独驱动
    某页时 switch_page 会抛(路径相对主脚本解析),但标记已持久化。

    注意:goto 应只在页面顶部(任何 widget 创建之前)调用。在 widget 之后
    (如按钮 handler 里)直接 goto 会让 AppTest 把当前页已渲染的 widget 悬空
    留在 tree 里,下次 run 序列化其 widget state 时 KeyError。跨页跳转请用
    request_nav()(置 pending_goto + rerun),由目标检查点 _consume_nav() 在
    下一 run 顶部执行真正的 switch_page。
    """
    st.session_state.current_page = page_key
    st.switch_page(PAGE_PATHS[page_key])


def request_nav(page_key: str) -> None:
    """请求跳转:置 pending_goto 并立即 rerun(不在此处 switch_page)。

    真正的 switch_page 延迟到目标页顶部 _consume_nav() 执行,确保 switch_page
    发生在任何 widget 创建之前。这样 AppTest 不会累积上一页的悬空 widget,
    避免 finalize 时 get_widget_states() 抛 KeyError。
    """
    st.session_state.pending_goto = page_key
    st.rerun()


def _consume_nav() -> None:
    """每页顶部(init_session_state 之后、任何 widget 之前)调用。

    若有 pending_goto 则在创建任何 widget 前 switch_page,消费掉标记。
    """
    target = st.session_state.get("pending_goto")
    if target:
        st.session_state.pending_goto = ""
        goto(target)


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
    "viewing_history": False,       # True 时报告页显示历史 session 只读视图
    "success_msg": "",              # 一次性提示(如"已保存到历史")
    # v0.3 Feature E: 真实性检测
    "turn_authenticity_flags": [],  # 每答一题追加一次:list[str],per-turn 启发式信号
    "authenticity_report": None,    # AuthenticityReport 或 None(报告末尾 LLM 聚合结果)
    # v0.3 alpha-kickoff: 成本
    "token_counter": None,          # DailyTokenCounter(懒初始化,见 _token_counter)
    # v0.3.1 专项练习:焦点主题模式
    "practice_mode": False,         # True 时启用专项练习 prompt 注入
    "practice_topic": "",           # 当前专项练习焦点主题
    # v0.3 multipage-navigation
    "current_page": "config",       # "config" | "interview" | "report"
    "pending_goto": "",             # 延迟跳转目标;由 _consume_nav 在页顶消费
    "pending_start": False,         # config 点开始后 → interview 页 auto-start 标记
    "pending_report_nav": False,    # 面试结束后 → interview 页顶部跳报告页标记
    # 测试 hook:mock_responses / mock_feedback_responses 不在 DEFAULTS,
    # 测试用 at.session_state[...] 显式注入(setdefault 不会覆盖已存在的键)。
}


def init_session_state() -> None:
    """幂等初始化所有 session_state 默认值(entry 与各 page 都可安全调用)。"""
    for k, v in DEFAULTS.items():
        st.session_state.setdefault(k, v)


# ============================================================================
# 面试自动存草稿(v0.3 Feature autosave):刷新 / 重进后能续答
# ============================================================================

# 仅序列化面试状态白名单(避免把 token_counter / pending_* 等 transient 写盘)
AUTOSAVE_KEYS = [
    "chat_history",
    "turn_feedback",
    "turn_authenticity_flags",
    "interview_level",
    "interview_style",
    "jd_content",
    "resume_content",
    "practice_mode",
    "practice_topic",
    "interview_started_at",
]


def _snapshot_state() -> dict:
    """按白名单取 session_state,datetime → isoformat 字符串。"""
    state: dict = {}
    for k in AUTOSAVE_KEYS:
        v = st.session_state.get(k)
        if hasattr(v, "isoformat"):
            v = v.isoformat()
        elif isinstance(v, list):
            v = list(v)  # 浅拷贝,避免引用共享
        state[k] = v
    return state


def _restore_state(state: dict) -> None:
    """白名单写回 session_state,isoformat → datetime。

    强制 interview_started=True / interview_ended=False / viewing_history=False,
    这样恢复后立刻进入对话循环,无需额外触发。
    """
    started_at_raw = state.get("interview_started_at")
    for k in AUTOSAVE_KEYS:
        v = state.get(k)
        if k == "interview_started_at" and isinstance(v, str):
            try:
                v = datetime.fromisoformat(v)
            except ValueError:
                v = None
        st.session_state[k] = v
    if started_at_raw is None:
        st.session_state.interview_started_at = datetime.now(timezone.utc)
    st.session_state.interview_started = True
    st.session_state.interview_ended = False
    st.session_state.viewing_history = False


def _autosave_interview() -> None:
    """进行中面试 → 写 autosave 行。best-effort,失败仅记日志。

    守卫:仅当 interview_started 且未结束 且未在查看历史时写,
    避免 _generate_report 之后 / viewing_history=True 时误写。
    """
    if not st.session_state.get("interview_started"):
        return
    if st.session_state.get("interview_ended"):
        return
    if st.session_state.get("viewing_history"):
        return
    try:
        save_autosave(None, get_candidate_id(), _snapshot_state())
    except Exception as _e:
        _log_error("autosave", _e)


def _clear_autosave() -> None:
    """面试完成后清草稿槽。best-effort,失败仅记日志。"""
    try:
        clear_autosave(None, get_candidate_id())
    except Exception as _e:
        _log_error("clear_autosave", _e)


def _log_error(tag: str, exc: Exception) -> None:
    """统一写 error.log(避免重复 try/except 噪音)。失败也吞掉。"""
    try:
        _ERROR_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _ERROR_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(
                f"[{datetime.now(timezone.utc).isoformat()}] {tag}: "
                f"{type(exc).__name__}: {str(exc)[:200]}\n"
                f"{'-' * 60}\n"
            )
    except Exception:
        pass


def _render_resume_prompt(*, target: str) -> bool:
    """检测草稿 → 渲染 banner + 继续/放弃按钮。返回 True(已渲染)。

    Args:
        target: 续答后跳到哪个页(目前固定 "interview")。

    仅当无进行中面试(interview_started=False)时展示,
    避免同 session 内重复提示。
    """
    if st.session_state.get("interview_started"):
        return False
    try:
        draft = load_autosave(None, get_candidate_id())
    except Exception:
        return False
    if not draft:
        return False

    n_turns = len(draft.get("chat_history", []))
    user_turns = sum(
        1 for m in draft.get("chat_history", []) if m.get("role") == "user"
    )

    st.info(
        f"🔄 发现一场未完成的面试({user_turns} 轮用户回答,{n_turns} 条消息)。"
        "是否继续?"
    )
    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("▶️ 继续面试", key="resume_continue", type="primary"):
            _restore_state(draft)
            st.rerun()
    with col_b:
        if st.button("🗑️ 放弃草稿", key="resume_discard", type="secondary"):
            _clear_autosave()
            st.rerun()
    return True


# ============================================================================
#  折叠渲染
# ============================================================================


def _split_think_blocks(content: str) -> tuple[list[str], str]:
    """把 ... 块从 LLM 输出中拆出来。

    Returns:
        (think_blocks, visible_content): 块列表 + 移除 think 后的可见内容(已 strip)
    """
    thinks = THINK_RE.findall(content)
    visible = THINK_RE.sub("", content).strip()
    return thinks, visible


def _render_message_body(content: str) -> None:
    """渲染 LLM 输出正文(把 ... 折叠到 expander 里)。"""
    thinks, visible = _split_think_blocks(content)
    if thinks:
        with st.expander(f"🧠 思考过程 ({len(thinks)} 块)", expanded=False):
            for i, t in enumerate(thinks, 1):
                if len(thinks) > 1:
                    st.markdown(f"**块 {i}**\n\n{t.strip()}")
                else:
                    st.markdown(t.strip())
    if visible:
        st.markdown(visible)


# ============================================================================
# LLM 调用 hook(测试注入点)
# ============================================================================

_chat_impl = chat
_chat_stream_impl = chat_stream


def _do_chat(messages, *, temperature=0.7, purpose="chat", stream=False):
    """调用 LLM。

    测试注入点:
    - purpose="chat"(默认):st.session_state["mock_responses"] 队列优先。
    - purpose="feedback":st.session_state["mock_feedback_responses"] 队列优先。
    streamlit rerun 不丢 session_state,所以这是稳定的测试 hook。
    """
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
        _token_counter().add(estimate_tokens(text))
        return text
    if stream and purpose == "chat":
        return _TrackingStream(_chat_stream_impl(messages, temperature=temperature))
    result = _chat_impl(messages, temperature=temperature)
    _token_counter().add(estimate_tokens(result))
    return result


class _TrackingStream:
    """包装 stream iterator,迭代结束时累加 output token。"""

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
        if self._buffer:
            _token_counter().add(estimate_tokens("".join(self._buffer)))
            self._buffer = []


def _token_counter() -> DailyTokenCounter:
    """懒初始化 token 计数器(确保 cap 与 env 同步)。"""
    if st.session_state.token_counter is None:
        st.session_state.token_counter = DailyTokenCounter(cap=get_daily_token_cap())
    else:
        st.session_state.token_counter.cap = get_daily_token_cap()
    return st.session_state.token_counter


# ============================================================================
# 全局异常处理 + 错误友好提示(v0.3 alpha-kickoff)
# ============================================================================


def _install_global_error_handler() -> None:
    """注册 sys.excepthook,记录未捕获异常。只记 type + 截断,不记 resume。"""

    def _hook(exc_type, exc_value, exc_tb):
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
            pass
    sys.excepthook = _hook


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
# 面试状态机
# ============================================================================


def _system_prompt() -> str:
    focus = (
        st.session_state.practice_topic
        if st.session_state.get("practice_mode") else None
    )
    return build_interviewer_system_prompt(
        level=st.session_state.interview_level,
        style=st.session_state.interview_style,
        resume=st.session_state.resume_content,
        jd=st.session_state.jd_content,
        focus_context=focus,
    )


def _start_interview() -> None:
    """开始面试:清空历史 + 流式生成第一题。

    practice_mode=True 时跳过 JD 非空校验(focus_context 替代 JD 提供训练方向)。
    在 pages/interview.py 的 auto-start trigger 里调用,流式渲染落在面试页。
    """
    is_practice = st.session_state.get("practice_mode", False)
    if not is_practice and not st.session_state.jd_content.strip():
        st.session_state.error_msg = "请先粘贴 JD 再开始面试"
        return
    st.session_state.chat_history = []
    st.session_state.turn_feedback = []
    st.session_state.turn_authenticity_flags = []
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
        {"role": "user", "content": "请开始专项练习" if is_practice else "请开始面试"},
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
    _autosave_interview()  # 第一题落地后写盘,刷新可续


def _handle_user_answer(answer: str, *, generate_next: bool = True) -> None:
    """用户提交回答:追加到 history → 逐轮反馈 → 可选流式生成下一题。"""
    st.session_state.chat_history.append({"role": "user", "content": answer})

    last_question = ""
    for msg in reversed(st.session_state.chat_history):
        if msg["role"] == "assistant":
            last_question = msg["content"]
            break

    # per-turn 启发式真实性信号检测(零 LLM 成本,<1ms)
    flags = detect_signals(
        question=last_question,
        answer=answer,
        resume_text=st.session_state.resume_content,
    )
    st.session_state.turn_authenticity_flags.append(flags)

    # 逐轮反馈(反馈 LLM 不流式)
    try:
        feedback_messages = [{
            "role": "user",
            "content": build_feedback_prompt(
                level=st.session_state.interview_level,
                question=last_question,
                answer=answer,
            ),
        }]
        # spinner 仅覆盖阻塞的 feedback LLM 调用;spinner 上下文退出后,
        # stream 下一题会自然接手视觉提示,不会与 chat_message 冲突。
        with st.spinner("💭 面试官思考中…"):
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

    if not generate_next:
        _autosave_interview()  # END_SIGNAL 分支:答完即写盘
        return

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
    _autosave_interview()  # 答完一轮 + 下一题落地后写盘


def _render_feedback_card(fb: dict, authenticity_flags: list[str] | None = None) -> None:
    """渲染反馈小卡:📊 N/10 — advice(浅灰底,单行)+ 可选 ⚠️ 真实性提示。"""
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

    st.subheader("💬 历史对话")
    feedback_by_idx = {
        f.get("turn_idx", i): f for i, f in enumerate(sess.get("feedback", []))
    }
    for i, msg in enumerate(sess["turns"]):
        if msg["role"] == "assistant":
            with st.chat_message("assistant", avatar="👨‍🏫"):
                _render_message_body(msg["content"])
        else:
            with st.chat_message("user", avatar="🙋"):
                st.markdown(msg["content"])
            fb = feedback_by_idx.get(i // 2)
            if fb and fb.get("score", -1) >= 0:
                _render_feedback_card(fb)

    if sess.get("report_text"):
        st.divider()
        st.subheader("📑 复盘报告")
        _render_message_body(sess["report_text"])
        st.download_button(
            "💾 下载报告 (Markdown)",
            data=sess["report_text"],
            file_name=f"interview_report_{sess['id']}.md",
            mime="text/markdown",
            key=f"dl_{sess['id']}",
        )


def _aggregate_authenticity() -> AuthenticityReport | None:
    """报告生成时调一次 LLM 聚合启发式 signals → AuthenticityReport。"""
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
    """生成报告「第 7 段 · 真实性维度」Markdown。失败/parse 错 → 空串。"""
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


def _generate_report() -> None:
    """结束面试,生成六维复盘报告,并自动落盘到历史。"""
    if not st.session_state.chat_history:
        st.session_state.error_msg = "还没有面试对话,无法生成报告"
        return
    prompt = prompts.build_report_prompt(
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

    # Feature E: 报告末尾追加真实性维度(单次 LLM 聚合;失败不阻断主报告)
    auth_report = _aggregate_authenticity()
    if auth_report is not None and auth_report.is_valid:
        st.session_state.authenticity_report = auth_report
        section_7 = _render_authenticity_section(auth_report)
        if section_7:
            st.session_state.report_text = report + "\n\n" + section_7

    # 落盘(失败不阻断 UI,但记 error_msg;报告仍可读可下载)
    try:
        sid = save_session(
            db_path=None,
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
            mode="practice" if st.session_state.get("practice_mode") else "interview",
        )
        st.session_state.current_session_id = sid
        st.session_state.success_msg = f"💾 已保存到历史 (id: {sid})"
        # 面试完成 → 草稿作废(防止下次开 app 误出续答 banner)
        _clear_autosave()
    except Exception as e:
        st.session_state.error_msg = f"报告已生成,但保存到历史失败:{e}"
