"""AI 面试官 (MVP) — 多页应用入口 (v0.3 multipage-navigation)。

启动:streamlit run app.py

本文件退化为 entry point,只负责:
1. 页面配置 + DB 初始化 + 全局异常 hook
2. session_state 初始化
3. 全局 sidebar(数据删除)
4. st.navigation 声明 4 页并 run

page-specific 渲染代码在 pages/*.py;跨页共享逻辑在 interview_helpers.py。
先 import interview_helpers 让它进 sys.modules,pages 再 import 即命中缓存。
"""
from __future__ import annotations

import streamlit as st

import interview_helpers  # noqa: F401 — 预热 sys.modules,供 pages import
from interview_helpers import (
    _install_global_error_handler,
    clear_all_sessions_for_candidate,
    get_candidate_id,
    get_retention_days,
    init_db,
    init_session_state,
    list_sessions,
    purge_expired_sessions,
)

st.set_page_config(
    page_title="AI 面试官 (MVP)",
    page_icon="🎯",
    layout="wide",
)

_install_global_error_handler()

# 数据库初始化(幂等 + mkdir);失败不阻断 UI
try:
    init_db()
    _retention = get_retention_days()
    if _retention > 0:
        purge_expired_sessions(None, _retention)
except Exception as _e:
    st.warning(f"⚠️ 历史数据库初始化失败:{_e}")

init_session_state()


# ============================================================================
# st.navigation 声明 4 页
# ============================================================================

pg = st.navigation([
    st.Page("pages/config.py", title="配置", icon="⚙️", default=True),
    st.Page("pages/interview.py", title="面试", icon="💬"),
    st.Page("pages/report.py", title="报告", icon="📑"),
    st.Page("pages/topics.py", title="训练图谱", icon="🎯"),
])


# ============================================================================
# 全局 sidebar(仅数据删除)
# ============================================================================

with st.sidebar:
    st.divider()
    with st.expander("🗑️ 清空我的全部历史", expanded=False):
        try:
            _cid = get_candidate_id()
            _n = len(list_sessions(None, _cid, limit=9999))
        except Exception:
            _n = 0
        st.caption(f"将永久删除你的全部 {_n} 条历史 session。")
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
                n = clear_all_sessions_for_candidate(None, get_candidate_id())
                st.session_state.success_msg = f"🗑️ 已清空 {n} 条历史 session"
                st.rerun()
            except Exception as e:
                st.error(f"清空失败:{e}")

pg.run()