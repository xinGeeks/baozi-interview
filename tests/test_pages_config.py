"""pages/config.py 集成测试 (Streamlit AppTest)。

覆盖:
- 渲染:简历上传 / JD / 等级 / 风格 / 预算 / 开始按钮
- 校验:JD 空 → 报错 + 不跳页
- 跳页:JD 填入 → 点开始 → 置 pending_start + request_nav("interview")

导航策略:统一从 app.py entry 进入,at.switch_page("pages/xxx.py") 跳页。
这样 st.switch_page 的路径解析(相对 main script)是正确的;直接 from_file
加载 pages/xxx.py 时 switch_page 路径以 pages/ 为根,跨页跳转失败。
"""
from __future__ import annotations

import os
from pathlib import Path

from streamlit.testing.v1 import AppTest

from storage import init_db


# ============================================================================
# 工具
# ============================================================================


def _config_page(db_path: Path) -> AppTest:
    """构造 AppTest 指向 config page,绑独立 DB。

    流程:AppTest.from_file("app.py") → switch_page("pages/config.py")
    → 注入测试 seed → run。
    """
    os.environ["STORAGE_DB_PATH"] = str(db_path)
    init_db(db_path)
    at = AppTest.from_file("app.py", default_timeout=10)
    at.run()
    at.switch_page("pages/config.py")
    at.run()
    return at


def _button_by_label(at: AppTest, needle: str):
    for b in at.button:
        if needle in str(b.label or ""):
            return b
    return None


# ============================================================================
# 渲染
# ============================================================================


class TestConfigPageRender:
    def test_page_title_renders(self, tmp_path: Path):
        db = tmp_path / "test.db"
        at = _config_page(db)
        titles = [t.value for t in at.title]
        assert any("配置面试" in t for t in titles), (
            f"期望『配置面试』标题,实际: {titles}"
        )

    def test_resume_uploader_present(self, tmp_path: Path):
        db = tmp_path / "test.db"
        at = _config_page(db)
        assert len(at.file_uploader) == 1, (
            f"期望 1 个 file_uploader,实际: {len(at.file_uploader)}"
        )
        assert "PDF" in (at.file_uploader[0].label or ""), (
            f"file_uploader 应支持 PDF,实际 label: {at.file_uploader[0].label}"
        )

    def test_jd_text_area_present(self, tmp_path: Path):
        db = tmp_path / "test.db"
        at = _config_page(db)
        labels = [t.label for t in at.text_area if t.label]
        assert any("JD" in lbl for lbl in labels), (
            f"期望 JD text_area,实际 labels: {labels}"
        )

    def test_level_selectbox_present(self, tmp_path: Path):
        db = tmp_path / "test.db"
        at = _config_page(db)
        labels = [s.label for s in at.selectbox if s.label]
        assert any("等级" in lbl for lbl in labels), (
            f"期望等级 selectbox,实际: {labels}"
        )

    def test_style_radio_present(self, tmp_path: Path):
        db = tmp_path / "test.db"
        at = _config_page(db)
        labels = [r.label for r in at.radio if r.label]
        assert any("风格" in lbl for lbl in labels), (
            f"期望风格 radio,实际: {labels}"
        )

    def test_llm_config_status_shown(self, tmp_path: Path):
        """LLM 模型名应在配置页可见(若已配置)。"""
        os.environ["LLM_API_KEY"] = "sk-test-fixture-key"
        db = tmp_path / "test.db"
        at = _config_page(db)
        captions = [c.value for c in at.caption]
        text_blob = "\n".join(captions) + "\n" + "\n".join(
            m.value for m in at.markdown
        )
        assert "模型" in text_blob or "LLM" in text_blob, (
            "期望 LLM 状态信息出现在 config 页"
        )

    def test_start_button_present(self, tmp_path: Path):
        db = tmp_path / "test.db"
        at = _config_page(db)
        btn = _button_by_label(at, "开始面试")
        assert btn is not None, "期望开始面试按钮"


# ============================================================================
# 校验
# ============================================================================


class TestConfigValidation:
    def test_empty_jd_shows_error(self, tmp_path: Path):
        """JD 为空时,点开始面试 → 报错 + 不请求跳转。"""
        db = tmp_path / "test.db"
        at = _config_page(db)
        at.session_state["jd_content"] = ""
        at.run()

        btn = _button_by_label(at, "开始面试")
        assert btn is not None
        btn.click()
        at.run()

        errors = [e.value for e in at.error]
        assert any("JD" in e for e in errors), (
            f"期望 JD 错误,实际 errors: {errors}"
        )
        # pending_start 不应被设
        assert (
            "pending_start" not in at.session_state
            or at.session_state["pending_start"] is False
        ), "JD 校验失败时不应触发跳转"

    def test_successful_start_triggers_navigation(self, tmp_path: Path):
        """JD 填入后,点开始 → 触发跳转(消费后应已在 interview 页 + auto-start 已跑)。"""
        db = tmp_path / "test.db"
        at = _config_page(db)
        at.session_state["mock_responses"] = ["第一题"]  # auto-start 需要 LLM 响应
        jd_ta = next(
            (t for t in at.text_area if "JD" in (t.label or "")), None
        )
        assert jd_ta is not None
        jd_ta.set_value("Python 后端 JD")
        at.run()

        btn = _button_by_label(at, "开始面试")
        btn.click()
        at.run()

        # 完整链路:config → interview + auto-start 在 at.run() 内已通过
        # request_nav → 切页 → _consume_nav → _start_interview 触达。
        assert at.session_state["current_page"] == "interview", (
            f"期望 current_page='interview',实际: "
            f"{at.session_state.get('current_page')!r}"
        )
        assert at.session_state["interview_started"] is True, (
            "期望 interview_started=True(auto-start 应触发)"
        )
        assert at.session_state["pending_goto"] == "", (
            f"期望 pending_goto 已消费,实际: "
            f"{at.session_state.get('pending_goto')!r}"
        )
        assert at.session_state["pending_start"] is False, (
            "期望 pending_start 已被 auto-start 消费"
        )
        assert len(at.session_state["chat_history"]) >= 1
        assert at.session_state["chat_history"][-1]["role"] == "assistant"


# ============================================================================
# session_state 语义
# ============================================================================


class TestSessionStateSemantics:
    def test_jd_value_round_trip(self, tmp_path: Path):
        """JD text_area 改值 → session_state['jd_content'] 同步。"""
        db = tmp_path / "test.db"
        at = _config_page(db)
        jd_ta = next(
            (t for t in at.text_area if "JD" in (t.label or "")), None
        )
        assert jd_ta is not None
        jd_ta.set_value("新的 JD 内容")
        at.run()
        assert at.session_state["jd_content"] == "新的 JD 内容"

    def test_level_selectbox_round_trip(self, tmp_path: Path):
        """等级 selectbox 选 P6 → session_state 更新。"""
        db = tmp_path / "test.db"
        at = _config_page(db)
        lvl_sb = next(
            (s for s in at.selectbox if "等级" in (s.label or "")), None
        )
        assert lvl_sb is not None
        opts = list(lvl_sb.options)
        target = next(o for o in opts if o != at.session_state["interview_level"])
        lvl_sb.set_value(target)
        at.run()
        assert at.session_state["interview_level"] == target

    def test_resume_content_round_trip(self, tmp_path: Path):
        """预设 resume_content → preview expander 渲染。"""
        db = tmp_path / "test.db"
        at = _config_page(db)
        at.session_state["resume_content"] = (
            "张三 5年 Python 后端 FastAPI 微服务 高并发"
        )
        at.run()

        expanders = [e for e in at.expander if "简历" in (e.label or "")]
        assert len(expanders) == 1
        assert "字" in expanders[0].label
        ta_values = [t.value for t in at.text_area]
        assert any("张三" in v and "Python" in v for v in ta_values)

    def test_no_resume_no_preview_expander(self, tmp_path: Path):
        """resume_content 空 → 无 preview expander。"""
        db = tmp_path / "test.db"
        at = _config_page(db)
        at.session_state["resume_content"] = ""
        at.run()
        expanders = [e for e in at.expander if "简历" in (e.label or "")]
        assert len(expanders) == 0


# ============================================================================
# 默认值
# ============================================================================


class TestDefaults:
    def test_default_level_is_mid(self, tmp_path: Path):
        """默认职级应为社招(中级)。"""
        db = tmp_path / "test.db"
        at = _config_page(db)
        assert "社招" in at.session_state["interview_level"], (
            f"默认职级应为社招(中级),实际: {at.session_state['interview_level']}"
        )

    def test_default_style_is_first_style(self, tmp_path: Path):
        """默认风格应为 STYLES[0](温和引导)。"""
        db = tmp_path / "test.db"
        at = _config_page(db)
        from prompts import STYLES
        assert at.session_state["interview_style"] == STYLES[0], (
            f"默认风格应为 {STYLES[0]},实际: {at.session_state['interview_style']}"
        )


# ============================================================================
# 专项练习交接 (v0.3.1:入口已挪到 pages/practice.py)
# ============================================================================


class TestPracticeHandoff:
    def test_config_has_no_practice_entry(self, tmp_path: Path):
        """配置页不应再自带专项练习启动按钮(入口在独立页)。"""
        at = _config_page(tmp_path / "test.db")
        assert _button_by_label(at, "启动专项练习") is None, (
            "专项练习入口应只在 pages/practice.py"
        )

    def test_config_points_to_practice_page(self, tmp_path: Path):
        """配置页应有一句指路到菜单栏专项练习页。"""
        at = _config_page(tmp_path / "test.db")
        text = "\n".join(c.value for c in at.caption)
        assert "专项练习" in text, f"应有指路 caption,实际: {text}"

    def test_normal_start_clears_practice_state(self, tmp_path: Path):
        """走正常『开始面试』应把 practice_mode 复位,避免残留串味。"""
        at = _config_page(tmp_path / "test.db")
        at.session_state["practice_mode"] = True
        at.session_state["practice_topic"] = "旧主题"
        at.session_state["mock_responses"] = ["请简单介绍一下你自己"]
        at.run()
        at.text_area[0].set_value("后端开发 JD").run()
        _button_by_label(at, "开始面试").click().run()

        assert at.session_state["practice_mode"] is False
        assert at.session_state["practice_topic"] == ""
