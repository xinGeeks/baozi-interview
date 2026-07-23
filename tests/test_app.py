"""app.py 集成测试 (Streamlit AppTest)。

驱动 UI 流程:配置 → 开始面试 → 回答 × N → 结束 → 报告。
LLM 用 session_state["mock_responses"] 注入预置响应,避免真 API 调用。
Streamlit rerun 不会丢 session_state,所以这个 hook 跨 rerun 稳定。
"""
from __future__ import annotations

import pytest
from streamlit.testing.v1 import AppTest

from prompts import END_SIGNAL
from tests.conftest import FakeLLM


# ============================================================================
# 工具
# ============================================================================

def _make_app(responses: list[str], **kwargs) -> tuple[AppTest, FakeLLM]:
    """构造 AppTest 并把 fake LLM 注入 session_state。

    v0.3 alpha-kickoff: 默认绕过 ToS modal(让测试聚焦在 app 主流程上)。
    测 ToS 自身的行为请用 tests/test_consent.py。
    """
    at = AppTest.from_file("app.py", default_timeout=10)
    # 在第一次 run 前注入 ToS 已接受(否则 modal 阻断所有 UI)
    at.session_state["tos_accepted"] = True
    at.session_state["tos_check_done"] = True
    at.run()
    # AppTest 第一次 run 后 session_state 才有;把 mock_responses 注入
    at.session_state["mock_responses"] = list(responses)
    fake = FakeLLM(list(responses))  # 记录用
    return at, fake


def _make_app_with_tos(responses: list[str] | None = None, **kwargs) -> tuple[AppTest, FakeLLM | None]:
    """构造 AppTest 但不绕过 ToS(用于测试 ToS 流程)。

    返回的 fake 在 tos 接受后才注入。
    """
    at = AppTest.from_file("app.py", default_timeout=10)
    at.session_state["tos_accepted"] = True
    at.session_state["tos_check_done"] = True
    at.run()
    fake = None
    if responses is not None:
        at.session_state["mock_responses"] = list(responses)
        fake = FakeLLM(list(responses))
    return at, fake


def _find_button(at: AppTest, predicate):
    return next((b for b in at.button if predicate(b.label)), None)


# ============================================================================
# 初始状态
# ============================================================================

def test_app_starts_without_error():
    at = AppTest.from_file("app.py", default_timeout=10)
    at.session_state["tos_accepted"] = True
    at.session_state["tos_check_done"] = True
    at.run()
    assert not at.exception, f"App 启动异常: {at.exception}"


def test_app_shows_title():
    at = AppTest.from_file("app.py", default_timeout=10)
    at.session_state["tos_accepted"] = True
    at.session_state["tos_check_done"] = True
    at.run()
    titles = [t.value for t in at.title]
    assert any("AI 面试官" in t for t in titles)


def test_sidebar_has_level_and_style_widgets():
    at = AppTest.from_file("app.py", default_timeout=10)
    at.session_state["tos_accepted"] = True
    at.session_state["tos_check_done"] = True
    at.run()
    assert any("面试等级" in (s.label or "") for s in at.selectbox)
    assert any("面试风格" in (r.label or "") for r in at.radio)


# ============================================================================
# 校验
# ============================================================================

def test_start_without_jd_shows_error(configure_llm):
    """没填 JD 时点开始,应当报错且不进入对话。"""
    at = AppTest.from_file("app.py", default_timeout=10)
    at.session_state["tos_accepted"] = True
    at.session_state["tos_check_done"] = True
    at.run()
    start_btn = _find_button(at, lambda l: "开始面试" in l and "重新" not in l)
    assert start_btn is not None
    start_btn.click()
    at.run()
    assert any("JD" in e.value for e in at.error)


def test_missing_api_key_warning(monkeypatch):
    """未配置 LLM_API_KEY 时,侧边栏应给出 warning。"""
    from config import LLMConfig
    monkeypatch.setattr("config.get_llm_config", lambda: LLMConfig(
        api_key="", base_url="x", model="y"
    ))
    at = AppTest.from_file("app.py", default_timeout=10)
    at.session_state["tos_accepted"] = True
    at.session_state["tos_check_done"] = True
    at.run()
    assert any("API" in w.value or "API_KEY" in w.value for w in at.warning)


# ============================================================================
# 完整流程:用 mock_responses 注入
# ============================================================================

def test_full_flow_start_answer_end_report(configure_llm):
    """开始 → 3 轮对话(第 3 轮触发结束)→ 报告生成。

    通过 session_state["mock_responses"] 注入 5 个预置响应:
    1) 开始面试第一题
    2) 候选人答 1 后的追问
    3) 候选人答 2 后的追问
    4) 候选人答 3(含"结束面试")后的终止语
    5) 报告
    """
    at = AppTest.from_file("app.py", default_timeout=10)
    at.session_state["tos_accepted"] = True
    at.session_state["tos_check_done"] = True
    at.run()
    responses = [
        "请介绍一下你自己",
        "好的,做过 5 年 Python,能讲讲最有挑战的项目吗?",
        "这个项目你具体负责什么模块?",
        "好的,本场模拟面试到此结束。",
        "## 复盘报告\n\n### 六维度打分\n1. 岗位匹配度:7/10 ...",
    ]
    at.session_state["mock_responses"] = list(responses)

    at.text_area[0].set_value("Python 后端开发,熟悉微服务")

    start_btn = _find_button(at, lambda l: "开始面试" in l and "重新" not in l)
    assert start_btn is not None
    start_btn.click()
    at.run()

    # 第一次回答
    assert len(at.chat_input) == 1, "开始后应出现 chat_input"
    at.chat_input[0].set_value("我做了 5 年 Python 后端")
    at.run()

    # 第二次回答
    at.chat_input[0].set_value("做过电商订单系统,峰值 QPS 5000")
    at.run()

    # 第三次回答(含结束关键词)
    at.chat_input[0].set_value(f"暂时想到这些,{END_SIGNAL}")
    at.run()

    # 期望 5 个 mock 全部用完
    remaining = at.session_state["mock_responses"] if "mock_responses" in at.session_state else []
    assert len(remaining) == 0, f"期望 mock 队列空,剩余 {len(remaining)} 个"

    # 报告区出现
    md = "\n".join(m.value for m in at.markdown)
    assert "复盘报告" in md or "六维度" in md


def test_explicit_end_button_triggers_report(configure_llm):
    """用户答完后点『结束面试』按钮,显式触发报告。"""
    at = AppTest.from_file("app.py", default_timeout=10)
    at.session_state["tos_accepted"] = True
    at.session_state["tos_check_done"] = True
    at.run()
    at.session_state["mock_responses"] = [
        "请介绍一下你自己",
        "好的,讲讲你做过的项目。",
        "## 复盘报告\n1. 岗位匹配度:6/10 ...",
    ]
    at.text_area[0].set_value("后端 JD")
    at.run()

    start_btn = _find_button(at, lambda l: "开始面试" in l and "重新" not in l)
    start_btn.click()
    at.run()

    at.chat_input[0].set_value("自我介绍")
    at.run()

    end_btn = _find_button(at, lambda l: "结束面试" in l and "开始" not in l)
    assert end_btn is not None
    end_btn.click()
    at.run()

    md = "\n".join(m.value for m in at.markdown)
    assert "复盘报告" in md


# ============================================================================
# 错误处理:用显式 LLMError 注入
# ============================================================================

def test_llm_error_during_start_shows_error(configure_llm, monkeypatch):
    """_do_chat 抛 LLMError 时,主应用展示错误,不崩溃。"""
    from llm import LLMError

    def boom(messages, **kwargs):
        raise LLMError("网络超时")

    # _do_chat 在 app 模块的 globals 里;Streamlit rerun 不会重新 import app.py,
    # 所以这个 monkeypatch 在整个测试期间都有效
    monkeypatch.setattr("app._do_chat", boom)

    at = AppTest.from_file("app.py", default_timeout=10)
    at.session_state["tos_accepted"] = True
    at.session_state["tos_check_done"] = True
    at.run()
    at.text_area[0].set_value("JD 内容")
    at.run()

    start_btn = _find_button(at, lambda l: "开始面试" in l and "重新" not in l)
    start_btn.click()
    at.run()

    errors = [e.value for e in at.error]
    assert any("LLM" in e or "网络" in e for e in errors), (
        f"期望出现 LLM 错误提示,实际 errors: {errors}"
    )


# ============================================================================
# 简历提取预览(v0.3 UX)
# ============================================================================

def test_resume_preview_expander_shows_content(configure_llm):
    """上传简历后,sidebar 应出现 expander 含简历全文。"""
    at = AppTest.from_file("app.py", default_timeout=10)
    at.session_state["tos_accepted"] = True
    at.session_state["tos_check_done"] = True
    at.run()
    # 直接灌 session_state 模拟已上传简历(绕开 file_uploader)
    at.session_state["resume_content"] = (
        "张三 5年 Python 后端 熟悉 FastAPI * 微服务 _ 高并发"
    )
    at.run()

    # expander 应出现且标签含"简历"和字数
    expanders = [e for e in at.sidebar.expander if "简历" in (e.label or "")]
    assert len(expanders) == 1, f"期望 1 个简历 expander,实际 {len(expanders)} 个"
    assert "字" in expanders[0].label
    # text_area 内容应含简历关键字(且 markdown 特殊字符不被吃)
    ta_values = [t.value for t in at.sidebar.text_area]
    assert any("张三" in v and "Python" in v for v in ta_values), (
        f"text_area 缺少简历关键字,实际: {ta_values}"
    )
    # markdown 特殊字符完整保留
    assert any("*" in v and "_" in v for v in ta_values), (
        "text_area 应完整保留 markdown 特殊字符(不被渲染)"
    )


def test_no_resume_preview_when_empty(configure_llm):
    """未上传简历时,不应出现简历预览 expander。"""
    at = AppTest.from_file("app.py", default_timeout=10)
    at.session_state["tos_accepted"] = True
    at.session_state["tos_check_done"] = True
    at.run()
    at.session_state["resume_content"] = ""
    at.run()
    expanders = [e for e in at.sidebar.expander if "简历" in (e.label or "")]
    assert len(expanders) == 0


# ============================================================================
# Think 块折叠(v0.3 UX)
# ============================================================================

class TestSplitThinkBlocks:
    """_split_think_blocks 纯函数测试。"""

    def test_no_think_block(self):
        from app import _split_think_blocks
        thinks, visible = _split_think_blocks("你好,我是回答")
        assert thinks == []
        assert visible == "你好,我是回答"

    def test_single_think_block_at_start(self):
        from app import _split_think_blocks
        content = "<think>我在思考怎么回答</think>\n\n正式回答"
        thinks, visible = _split_think_blocks(content)
        assert len(thinks) == 1
        assert "我在思考怎么回答" in thinks[0]
        assert visible == "正式回答"

    def test_multiple_think_blocks(self):
        from app import _split_think_blocks
        content = "<think>第一段思考</think>中段可见<think>第二段思考</think>"
        thinks, visible = _split_think_blocks(content)
        assert len(thinks) == 2
        assert "第一段" in thinks[0]
        assert "第二段" in thinks[1]
        assert "中段可见" in visible

    def test_think_with_multiline(self):
        from app import _split_think_blocks
        content = "<think>第一行\n第二行\n第三行</think>\n\n回答"
        thinks, visible = _split_think_blocks(content)
        assert len(thinks) == 1
        assert "第一行" in thinks[0]
        assert "第二行" in thinks[0]
        assert "第三行" in thinks[0]
        assert visible == "回答"

    def test_think_only_no_visible(self):
        from app import _split_think_blocks
        thinks, visible = _split_think_blocks("<think>只有思考</think>")
        assert len(thinks) == 1
        assert visible == ""


def test_chat_history_with_think_shows_expander(configure_llm):
    """chat_history 含 <think> 块时,渲染应出现折叠 expander。"""
    at = AppTest.from_file("app.py", default_timeout=10)
    at.session_state["tos_accepted"] = True
    at.session_state["tos_check_done"] = True
    at.run()
    at.session_state["chat_history"] = [
        {"role": "user", "content": "自我介绍"},
        {
            "role": "assistant",
            "content": "<think>他在让我自我介绍,我要问项目</think>\n\n请介绍一下你自己和最有挑战的项目",
        },
    ]
    at.run()

    # 应出现"思考过程"expander
    think_expanders = [e for e in at.expander if "思考" in (e.label or "")]
    assert len(think_expanders) == 1
    # visible 部分仍渲染
    md = "\n".join(m.value for m in at.markdown)
    assert "请介绍一下你自己" in md
    # 思考内容不应在 markdown 里(在 expander 里)
    assert "我在思考" not in md or "思考过程" in md  # 思考被 expander 收纳


def test_chat_history_without_think_no_expander(configure_llm):
    """chat_history 无 <think> 时,不应出现思考 expander。"""
    at = AppTest.from_file("app.py", default_timeout=10)
    at.session_state["tos_accepted"] = True
    at.session_state["tos_check_done"] = True
    at.run()
    at.session_state["chat_history"] = [
        {"role": "user", "content": "自我介绍"},
        {"role": "assistant", "content": "请介绍一下你自己"},
    ]
    at.run()
    think_expanders = [e for e in at.expander if "思考" in (e.label or "")]
    assert len(think_expanders) == 0


# ============================================================================
# v0.3 alpha-kickoff fix:复盘报告渲染
# - think 块折叠(同 chat 消息)
# - 历史视图下不再与主报告区重复渲染
# ============================================================================

def test_report_with_think_shows_expander(configure_llm):
    """report_text 含 <think> 块时,渲染应折叠到 expander 里(同 chat 消息行为)。"""
    at = AppTest.from_file("app.py", default_timeout=10)
    at.session_state["tos_accepted"] = True
    at.session_state["tos_check_done"] = True
    at.run()
    at.session_state["report_text"] = (
        "<think>内部评估:候选人回答偏弱</think>\n\n"
        "## 1. 整体评价\n\n候选人表达清晰。"
    )
    at.run()

    # 应出现"思考过程"expander(折叠收纳)
    think_expanders = [e for e in at.expander if "思考" in (e.label or "")]
    assert len(think_expanders) == 1
    # visible 部分(标题 + 段落)照常渲染
    md = "\n".join(m.value for m in at.markdown)
    assert "整体评价" in md
    assert "候选人表达清晰" in md


def test_report_without_think_no_expander(configure_llm):
    """report_text 不含 <think> 时,不应出现报告折叠 expander。"""
    at = AppTest.from_file("app.py", default_timeout=10)
    at.session_state["tos_accepted"] = True
    at.session_state["tos_check_done"] = True
    at.run()
    at.session_state["report_text"] = "## 1. 整体评价\n\n候选人表达清晰。"
    at.run()

    # 报告区出现,但无 think expander
    labels = [s.value for s in at.subheader if s.value]
    assert any("面试复盘报告" in lbl for lbl in labels)
    think_expanders = [e for e in at.expander if "思考" in (e.label or "")]
    assert len(think_expanders) == 0


def test_history_view_chat_think_folded(configure_llm, monkeypatch, tmp_path):
    """历史对话视图里的 assistant 消息若含 <think>,也应折叠到 expander。"""
    from datetime import datetime, timezone
    from storage import init_db, save_session

    db_path = tmp_path / "test.db"
    init_db(db_path)
    monkeypatch.setenv("STORAGE_DB_PATH", str(db_path))

    at = AppTest.from_file("app.py", default_timeout=10)
    at.session_state["tos_accepted"] = True
    at.session_state["tos_check_done"] = True
    at.run()

    sid = save_session(
        db_path=db_path,
        level="P5",
        style="严谨",
        jd="Python 后端 JD",
        resume_text="张三 简历",
        chat_history=[
            {"role": "user", "content": "自我介绍"},
            {
                "role": "assistant",
                "content": (
                    "<think>他在让我做自我介绍,先问项目</think>\n\n"
                    "请介绍一下你自己和最有挑战的项目"
                ),
            },
        ],
        turn_feedback=[],
        report_text="",
        started_at=datetime.now(timezone.utc),
    )

    at.session_state["loaded_session_id"] = sid
    at.session_state["viewing_history"] = True
    at.run()

    # 历史视图里应出现"思考过程"expander
    think_expanders = [e for e in at.expander if "思考" in (e.label or "")]
    assert len(think_expanders) == 1, (
        f"历史对话视图应折叠 think 块,实际 expander 数:{len(think_expanders)}"
    )
    # visible 部分照常渲染
    md = "\n".join(m.value for m in at.markdown)
    assert "请介绍一下你自己" in md


def test_history_view_does_not_duplicate_report(configure_llm, monkeypatch, tmp_path):
    """进入历史会话视图时,主报告区不应再渲染同一份报告(避免重复展示)。"""
    from datetime import datetime, timezone
    from storage import init_db, save_session

    db_path = tmp_path / "test.db"
    init_db(db_path)
    monkeypatch.setenv("STORAGE_DB_PATH", str(db_path))

    at = AppTest.from_file("app.py", default_timeout=10)
    at.session_state["tos_accepted"] = True
    at.session_state["tos_check_done"] = True
    at.run()

    # 落一份历史(含报告)
    sid = save_session(
        db_path=db_path,
        level="P5",
        style="严谨",
        jd="Python 后端 JD",
        resume_text="张三 简历",
        chat_history=[
            {"role": "user", "content": "q"},
            {"role": "assistant", "content": "a"},
        ],
        turn_feedback=[],
        report_text="## 1. 整体评价\n\n历史报告内容",
        started_at=datetime.now(timezone.utc),
    )

    # 模拟"结束面试 → 主报告已渲染"的 state(report_text 已设)
    at.session_state["report_text"] = "## 当前报告\n\n当前会话报告内容"
    at.session_state["loaded_session_id"] = sid
    at.session_state["viewing_history"] = True
    at.run()

    # 主区:不应出现「面试复盘报告」(只显示历史视图的「复盘报告」)
    subheaders = [s.value for s in at.subheader if s.value]
    main_report_titles = [s for s in subheaders if "面试复盘报告" in s]
    history_report_titles = [s for s in subheaders if s.strip() == "📑 复盘报告"]
    assert len(main_report_titles) == 0, (
        f"主报告区不应渲染,实际 subheaders: {subheaders}"
    )
    assert len(history_report_titles) == 1, (
        f"历史视图应渲染一份『复盘报告』,实际 subheaders: {subheaders}"
    )

    # markdown 池里:历史报告内容出现,当前会话报告内容不出现
    md = "\n".join(m.value for m in at.markdown)
    assert "历史报告内容" in md
    assert "当前会话报告内容" not in md


def test_delete_popover_confirm_removes_session(configure_llm, monkeypatch, tmp_path):
    """🗑️ popover → 点「确认删除」→ session 删掉 + 成功提示渲染。

    AppTest 把 popover body 内的按钮直接暴露在 at.sidebar.button(无需先
    「打开」popover),所以可以直接定位 key=del_{sid} 的按钮并 click。
    """
    from datetime import datetime, timezone
    from storage import get_session, init_db, save_session

    db_path = tmp_path / "test.db"
    init_db(db_path)
    monkeypatch.setenv("STORAGE_DB_PATH", str(db_path))

    at = AppTest.from_file("app.py", default_timeout=10)
    at.session_state["tos_accepted"] = True
    at.session_state["tos_check_done"] = True
    at.run()

    sid_target = save_session(
        db_path=db_path, level="P5", style="严谨",
        jd="JD A", resume_text="张三",
        chat_history=[{"role": "user", "content": "q"},
                      {"role": "assistant", "content": "a"}],
        turn_feedback=[], report_text="r",
        started_at=datetime.now(timezone.utc),
    )
    sid_keep = save_session(
        db_path=db_path, level="P5", style="严谨",
        jd="JD B", resume_text="李四",
        chat_history=[{"role": "user", "content": "q"},
                      {"role": "assistant", "content": "a"}],
        turn_feedback=[], report_text="r",
        started_at=datetime.now(timezone.utc),
    )
    at.run()

    # popover body 里的「确认删除」按钮
    del_btns = [
        b for b in at.sidebar.button if b.key == f"del_{sid_target}"
    ]
    assert len(del_btns) == 1, (
        f"popover body 里的「确认删除」按钮应渲染,实际: "
        f"{[(b.label, b.key) for b in at.sidebar.button]}"
    )

    # 点确认删除
    del_btns[0].click()
    at.run()

    # 1) DB 里 sid_target 已删,sid_keep 仍在
    assert get_session(db_path, sid_target) is None
    assert get_session(db_path, sid_keep) is not None

    # 2) 成功提示渲染
    success_messages = [s.value for s in at.success]
    assert any("已删除" in m for m in success_messages), (
        f"未看到删除成功提示,at.success: {success_messages}"
    )

def test_feedback_card_appears_after_user_message(configure_llm):
    """跑 2 轮对话,每轮 user message 后应出现反馈小卡。"""
    at = AppTest.from_file("app.py", default_timeout=10)
    at.session_state["tos_accepted"] = True
    at.session_state["tos_check_done"] = True
    at.run()
    # 主对话 3 个 mock(开场 + 2 个追问)+ 2 个反馈 mock
    at.session_state["mock_responses"] = [
        "请介绍一下你自己",
        "做过最有挑战的项目是?",
        "团队规模和你的具体职责?",
    ]
    at.session_state["mock_feedback_responses"] = [
        "【分数】7/10\n【建议】回答里有项目但缺数据,补一个量化数字。",
        "【分数】5/10\n【建议】描述模糊,具体说说你负责的模块。",
    ]
    at.text_area[0].set_value("Python 后端 JD")
    at.run()

    start_btn = _find_button(at, lambda l: "开始面试" in l and "重新" not in l)
    start_btn.click()
    at.run()

    # 第 1 轮
    at.chat_input[0].set_value("我做电商订单系统 5 年")
    at.run()

    # 第 2 轮
    at.chat_input[0].set_value("团队 8 人,我负责订单核心模块")
    at.run()

    # 两轮反馈应进入队列
    assert len(at.session_state["turn_feedback"]) == 2
    assert at.session_state["turn_feedback"][0]["score"] == 7
    assert "量化" in at.session_state["turn_feedback"][0]["advice"]
    assert at.session_state["turn_feedback"][1]["score"] == 5

    # 渲染层:HTML 卡片 div 含分数和建议
    html_md = "\n".join(m.value for m in at.markdown)
    assert "7/10" in html_md
    assert "5/10" in html_md
    assert "📊" in html_md


def test_feedback_failure_does_not_break_interview(configure_llm, monkeypatch):
    """反馈 LLM 抛错时,主对话下一题仍正常生成。"""
    import streamlit as st
    from llm import LLMError

    def selective_chat(messages, *, temperature=0.7, purpose="chat"):
        if purpose == "feedback":
            raise LLMError("反馈服务挂了")
        mock_q = st.session_state.get("mock_responses")
        if isinstance(mock_q, list) and mock_q:
            return mock_q.pop(0)
        return ""

    monkeypatch.setattr("app._do_chat", selective_chat)

    at = AppTest.from_file("app.py", default_timeout=10)
    at.session_state["tos_accepted"] = True
    at.session_state["tos_check_done"] = True
    at.run()
    at.session_state["mock_responses"] = ["开场问题", "追问"]
    at.text_area[0].set_value("JD")
    at.run()

    start_btn = _find_button(at, lambda l: "开始面试" in l and "重新" not in l)
    start_btn.click()
    at.run()

    at.chat_input[0].set_value("我的回答")
    at.run()

    # 反馈失败被吞,但 turn_feedback 应有 score=-1 占位
    assert len(at.session_state["turn_feedback"]) == 1
    assert at.session_state["turn_feedback"][0]["score"] == -1

    # 主对话下一题应出现
    history = at.session_state["chat_history"]
    last_msg = history[-1]
    assert last_msg["role"] == "assistant"
    assert last_msg["content"]  # 非空

    # 错误信息不应展示(因为我们吞了 LLMError)
    assert not at.error


def test_turn_feedback_passed_to_report_prompt(configure_llm, monkeypatch):
    """结束面试时,turn_feedback 应透传给 build_report_prompt。

    注意:monkeypatch `app.build_report_prompt` 不稳(Streamlit rerun 重新
    执行 from prompts import ... 会覆盖 patch);改 patch 源模块 prompts。
    """
    captured = {}

    def fake_report_prompt(*args, **kwargs):
        captured["turn_feedback"] = kwargs.get("turn_feedback")
        captured["called"] = True
        return "REPORT_PROMPT_STUB"

    monkeypatch.setattr("prompts.build_report_prompt", fake_report_prompt)

    at = AppTest.from_file("app.py", default_timeout=10)
    at.session_state["tos_accepted"] = True
    at.session_state["tos_check_done"] = True
    at.run()
    at.session_state["mock_responses"] = [
        "开场", "追问", "## 复盘报告"
    ]
    at.session_state["mock_feedback_responses"] = [
        "【分数】8/10\n【建议】不错。",
        "【分数】6/10\n【建议】再具体。",
    ]
    at.text_area[0].set_value("JD")
    at.run()

    start_btn = _find_button(at, lambda l: "开始面试" in l and "重新" not in l)
    start_btn.click()
    at.run()
    at.chat_input[0].set_value("answer 1")
    at.run()
    at.chat_input[0].set_value("answer 2")
    at.run()

    end_btn = _find_button(at, lambda l: "结束面试" in l and "开始" not in l)
    end_btn.click()
    at.run()

    assert captured.get("called") is True
    tf = captured.get("turn_feedback")
    assert tf is not None
    assert len(tf) == 2
    assert tf[0]["score"] == 8
    assert tf[1]["score"] == 6


# ============================================================================
# v0.3 Feature B:面试历史持久化
# ============================================================================

def test_report_auto_saved_to_db(configure_llm, monkeypatch, tmp_path):
    """跑完一场面试,报告生成后应自动写入 SQLite。

    AppTest 在子进程跑 app.py,monkeypatch 不会传过去;
    改用 STORAGE_DB_PATH 环境变量,storage.py 启动时读它。
    """
    import sqlite3
    from storage import init_db

    db_path = tmp_path / "test.db"
    init_db(db_path)
    monkeypatch.setenv("STORAGE_DB_PATH", str(db_path))

    at = AppTest.from_file("app.py", default_timeout=10)
    at.session_state["tos_accepted"] = True
    at.session_state["tos_check_done"] = True
    at.run()
    at.session_state["mock_responses"] = [
        "开场问题",
        "追问 1",
        "## 复盘报告\n1. 岗位匹配度:7/10 ...",
    ]
    at.session_state["mock_feedback_responses"] = [
        "【分数】8/10\n【建议】不错。",
    ]
    at.text_area[0].set_value("JD 内容")
    at.run()

    start_btn = _find_button(at, lambda l: "开始面试" in l and "重新" not in l)
    start_btn.click()
    at.run()
    at.chat_input[0].set_value("我的回答")
    at.run()

    end_btn = _find_button(at, lambda l: "结束面试" in l and "开始" not in l)
    end_btn.click()
    at.run()

    # current_session_id 应已填
    assert at.session_state["current_session_id"] != ""

    # DB 应有 1 行
    with sqlite3.connect(str(db_path)) as conn:
        rows = conn.execute(
            "SELECT id, level, turn_count FROM interview_sessions"
        ).fetchall()
    assert len(rows) == 1
    assert rows[0][1] == "社招(中级)"  # DEFAULTS 默认
    assert rows[0][2] == 1  # 1 个 user turn


def test_history_sidebar_lists_saved_sessions(configure_llm, monkeypatch, tmp_path):
    """保存一场后,sidebar「📚 历史面试」区应出现历史按钮。"""
    from storage import init_db, save_session
    from datetime import datetime, timezone

    db_path = tmp_path / "test.db"
    init_db(db_path)
    monkeypatch.setenv("STORAGE_DB_PATH", str(db_path))

    # 预先写一场(显式传 ended_at,这样 sidebar label 的日期才是 2026-07-21)
    save_session(
        db_path=db_path,
        level="校招", style="温和引导",
        jd="JD", resume_text="",
        chat_history=[
            {"role": "assistant", "content": "q"},
            {"role": "user", "content": "a"},
        ],
        turn_feedback=[{"question": "q", "score": 7, "advice": "x"}],
        report_text="R",
        started_at=datetime(2026, 7, 21, tzinfo=timezone.utc),
        ended_at=datetime(2026, 7, 21, 12, 0, 0, tzinfo=timezone.utc),
    )

    at = AppTest.from_file("app.py", default_timeout=10)
    at.session_state["tos_accepted"] = True
    at.session_state["tos_check_done"] = True
    at.run()

    # sidebar 应出现历史按钮(label 含日期 + 等级 + 轮次)
    sidebar_buttons = [b.label for b in at.sidebar.button]
    assert any(
        "2026-07-21" in lbl and "校招" in lbl and "1 轮" in lbl
        for lbl in sidebar_buttons
    ), f"历史按钮缺失,实际: {sidebar_buttons}"


def test_load_history_renders_readonly_view(configure_llm, monkeypatch, tmp_path):
    """点历史按钮,主区出现历史对话 + 「← 返回新面试」按钮。"""
    from datetime import datetime, timezone
    from storage import init_db, save_session

    db_path = tmp_path / "test.db"
    init_db(db_path)
    monkeypatch.setenv("STORAGE_DB_PATH", str(db_path))

    save_session(
        db_path=db_path,
        level="校招", style="温和引导",  # 用"校招"匹配 test_history_sidebar 的预期
        jd="JD", resume_text="",
        chat_history=[
            {"role": "assistant", "content": "你好,请自我介绍"},
            {"role": "user", "content": "我做 Python 后端"},
        ],
        turn_feedback=[],
        report_text="## 复盘报告\n1. 沟通:7/10",
        started_at=datetime(2026, 7, 21, tzinfo=timezone.utc),
        ended_at=datetime(2026, 7, 21, 12, 0, 0, tzinfo=timezone.utc),
    )

    at = AppTest.from_file("app.py", default_timeout=10)
    at.session_state["tos_accepted"] = True
    at.session_state["tos_check_done"] = True
    at.run()

    # 找历史按钮并点
    hist_btns = [
        b for b in at.sidebar.button
        if "2026-07-21" in (b.label or "")
    ]
    assert len(hist_btns) >= 1
    hist_btns[0].click()
    at.run()

    # viewing_history 应为 True
    assert at.session_state["viewing_history"] is True
    assert at.session_state["loaded_session_id"] != ""

    # 「← 返回新面试」按钮出现
    all_labels = [b.label for b in at.button]
    assert any("返回新面试" in lbl for lbl in all_labels)

    # 历史对话内容出现
    md = "\n".join(m.value for m in at.markdown)
    assert "你好,请自我介绍" in md or "复盘报告" in md


def test_no_resume_text_persisted(configure_llm, monkeypatch, tmp_path):
    """简历原文不应落盘(只存 hash)。"""
    import sqlite3
    from storage import init_db

    db_path = tmp_path / "test.db"
    init_db(db_path)
    monkeypatch.setenv("STORAGE_DB_PATH", str(db_path))

    at = AppTest.from_file("app.py", default_timeout=10)
    at.session_state["tos_accepted"] = True
    at.session_state["tos_check_done"] = True
    at.run()
    at.session_state["resume_content"] = (
        "张三_PII_SECRET_身份证_11010119900101_简历内容"
    )
    at.session_state["mock_responses"] = [
        "q", "## 复盘报告\nx",
    ]
    at.text_area[0].set_value("JD")
    at.run()

    start_btn = _find_button(at, lambda l: "开始面试" in l and "重新" not in l)
    start_btn.click()
    at.run()

    end_btn = _find_button(at, lambda l: "结束面试" in l and "开始" not in l)
    end_btn.click()
    at.run()

    # 全文扫描 DB
    with sqlite3.connect(str(db_path)) as conn:
        all_text = ""
        for table in ("interview_sessions", "interview_turns", "turn_feedback"):
            rows = conn.execute(f"SELECT * FROM {table}").fetchall()
            for r in rows:
                all_text += str(r) + "\n"

    assert "张三_PII_SECRET" not in all_text
    assert "11010119900101" not in all_text


# ============================================================================
# v0.3 Feature E: 真实性检测(per-turn ⚠️ + 报告第 7 段)
# ============================================================================


def test_feedback_card_shows_warning_when_flags_present(configure_llm):
    """turn_authenticity_flags 非空时,反馈卡渲染 ⚠️ + flag 文本。"""
    at = AppTest.from_file("app.py", default_timeout=10)
    at.session_state["tos_accepted"] = True
    at.session_state["tos_check_done"] = True
    at.run()
    at.session_state["chat_history"] = [
        {"role": "assistant", "content": "介绍一下你的项目"},
        {"role": "user", "content": "我做过。"},
    ]
    at.session_state["turn_feedback"] = [
        {"question": "介绍一下你的项目", "score": 5, "advice": "补具体细节"},
    ]
    at.session_state["turn_authenticity_flags"] = [["过于简短"]]
    at.run()

    md = "\n".join(m.value for m in at.markdown)
    assert "⚠️" in md, f"期望 ⚠️ 在 markdown 中,实际: {md[:300]}"
    assert "过于简短" in md


def test_feedback_card_omits_warning_when_flags_empty(configure_llm):
    """turn_authenticity_flags 为空时,反馈卡不渲染 ⚠️。"""
    at = AppTest.from_file("app.py", default_timeout=10)
    at.session_state["tos_accepted"] = True
    at.session_state["tos_check_done"] = True
    at.run()
    at.session_state["chat_history"] = [
        {"role": "assistant", "content": "介绍一下你的项目"},
        {"role": "user", "content": "我做了一个电商订单系统,QPS 5000。"},
    ]
    at.session_state["turn_feedback"] = [
        {"question": "介绍一下你的项目", "score": 7, "advice": "数据具体"},
    ]
    at.session_state["turn_authenticity_flags"] = [[]]
    at.run()

    md = "\n".join(m.value for m in at.markdown)
    assert "⚠️" not in md, f"不应出现 ⚠️,实际: {md[:300]}"
    # 反馈卡的分数 / 建议仍渲染
    assert "7/10" in md
    assert "数据具体" in md


def test_report_renders_section_7_when_authenticity_valid(configure_llm, monkeypatch, tmp_path):
    """authenticity_report score=0.7 时,报告末尾追加第 7 段。"""
    from authenticity import AuthenticityReport, Finding
    from app import _render_authenticity_section

    # 直接调纯函数渲染,不依赖真实 LLM
    report = AuthenticityReport(
        score=0.7,
        findings=[Finding(turn=2, issue="答非所问", detail="问项目却聊生活")],
        summary="整体一致性一般",
    )
    md = _render_authenticity_section(report)
    assert "真实性" in md
    assert "70" in md  # 0.7 * 100 = 70
    assert "答非所问" in md
    assert "整体一致性一般" in md


def test_report_hides_section_7_when_parse_failed(configure_llm):
    """authenticity_report score=-1( sentinel)时,不渲染第 7 段。"""
    from authenticity import AuthenticityReport
    from app import _render_authenticity_section

    report = AuthenticityReport(score=-1.0, summary="LLM 解析失败")
    md = _render_authenticity_section(report)
    assert md == "", f"sentinel 应返回空串,实际: {md[:200]}"


def test_report_end_to_end_includes_section_7(configure_llm, monkeypatch, tmp_path):
    """完整流程跑下来,score=0.7 时报告含第 7 段。"""
    db_path = tmp_path / "test.db"
    db_path.parent.mkdir(exist_ok=True)
    monkeypatch.setenv("STORAGE_DB_PATH", str(db_path))

    at = AppTest.from_file("app.py", default_timeout=10)
    at.session_state["tos_accepted"] = True
    at.session_state["tos_check_done"] = True
    at.run()
    # 4 chat + 1 report + 1 authenticity = 6 mock 响应
    responses = [
        "请介绍一下你自己",                                # 1. 第一题
        "好的,讲讲项目",                                  # 2. 追问 1
        "这个项目你具体负责什么?",                         # 3. 追问 2
        "好的,本场模拟面试到此结束。",                    # 4. 结束语
        "## 复盘报告\n\n### 六维度打分\n1. 沟通:7/10",   # 5. 报告
        '{"score": 0.7, "findings": [{"turn": 1, "issue": "模板化", "detail": "泛词无数据"}], "summary": "整体可改进"}',  # 6. 真实性聚合
    ]
    at.session_state["mock_responses"] = list(responses)
    at.session_state["resume_content"] = "张三 5年 Python 后端 订单系统 MySQL 高并发"

    at.text_area[0].set_value("Python 后端 JD")
    start_btn = _find_button(at, lambda l: "开始面试" in l and "重新" not in l)
    start_btn.click()
    at.run()

    # 3 轮对话
    at.chat_input[0].set_value("我做了 5 年 Python 后端")
    at.run()
    at.chat_input[0].set_value("做过订单系统")  # 短答,触发"过于简短"flag
    at.run()
    at.chat_input[0].set_value(f"暂时想到这些,{END_SIGNAL}")
    at.run()

    # 报告应已生成,含第 7 段
    assert at.session_state["report_text"], "报告未生成"
    assert "真实性" in at.session_state["report_text"]
    assert "70" in at.session_state["report_text"]
    assert "模板化" in at.session_state["report_text"]

    # authenticity_report 也存进 session_state
    auth = at.session_state["authenticity_report"]
    assert auth is not None
    assert auth.score == 0.7
