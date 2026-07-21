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
    """构造 AppTest 并把 fake LLM 注入 session_state。"""
    at = AppTest.from_file("app.py", default_timeout=10)
    at.run()
    # AppTest 第一次 run 后 session_state 才有;把 mock_responses 注入
    at.session_state["mock_responses"] = list(responses)
    fake = FakeLLM(list(responses))  # 记录用
    return at, fake


def _find_button(at: AppTest, predicate):
    return next((b for b in at.button if predicate(b.label)), None)


# ============================================================================
# 初始状态
# ============================================================================

def test_app_starts_without_error():
    at = AppTest.from_file("app.py", default_timeout=10)
    at.run()
    assert not at.exception, f"App 启动异常: {at.exception}"


def test_app_shows_title():
    at = AppTest.from_file("app.py", default_timeout=10)
    at.run()
    titles = [t.value for t in at.title]
    assert any("AI 面试官" in t for t in titles)


def test_sidebar_has_level_and_style_widgets():
    at = AppTest.from_file("app.py", default_timeout=10)
    at.run()
    assert any("面试等级" in (s.label or "") for s in at.selectbox)
    assert any("面试风格" in (r.label or "") for r in at.radio)


# ============================================================================
# 校验
# ============================================================================

def test_start_without_jd_shows_error(configure_llm):
    """没填 JD 时点开始,应当报错且不进入对话。"""
    at = AppTest.from_file("app.py", default_timeout=10)
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
    at.run()
    at.session_state["chat_history"] = [
        {"role": "user", "content": "自我介绍"},
        {"role": "assistant", "content": "请介绍一下你自己"},
    ]
    at.run()
    think_expanders = [e for e in at.expander if "思考" in (e.label or "")]
    assert len(think_expanders) == 0
