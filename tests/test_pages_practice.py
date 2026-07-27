"""pages/practice.py 集成测试 (Streamlit AppTest)。

覆盖:
- 渲染:标题 / 主题输入框 / 难度 / 风格 / 启动按钮
- 校验:主题空 → 按钮 disabled(不需要 JD)
- 启动:填主题 → 点启动 → practice_mode + practice_topic + pending_start
"""
from __future__ import annotations

import os
from pathlib import Path

from streamlit.testing.v1 import AppTest

from storage import init_db


def _practice_page(db_path: Path) -> AppTest:
    """从 entry 进入再 switch_page,保证 switch_page 路径相对主脚本解析。"""
    os.environ["STORAGE_DB_PATH"] = str(db_path)
    init_db(db_path)
    at = AppTest.from_file("app.py", default_timeout=30)
    at.run()
    at.switch_page("pages/practice.py")
    at.run()
    return at


def _button_by_label(at: AppTest, needle: str):
    return next((b for b in at.button if needle in str(b.label or "")), None)


class TestPracticePageRender:
    def test_title_renders(self, tmp_path: Path):
        at = _practice_page(tmp_path / "test.db")
        titles = [t.value for t in at.title]
        assert any("专项练习" in t for t in titles), (
            f"期望『专项练习』标题,实际: {titles}"
        )
        assert at.session_state["current_page"] == "practice"

    def test_topic_input_present(self, tmp_path: Path):
        at = _practice_page(tmp_path / "test.db")
        keys = [ti.key for ti in at.text_input]
        assert "practice_topic_input" in keys, f"缺主题输入框,实际: {keys}"

    def test_level_and_style_widgets_present(self, tmp_path: Path):
        at = _practice_page(tmp_path / "test.db")
        assert len(at.selectbox) >= 1, "应有难度 selectbox"
        assert len(at.radio) >= 1, "应有风格 radio"

    def test_no_jd_textarea(self, tmp_path: Path):
        """专项练习不需要 JD,不应出现 JD 输入区。"""
        at = _practice_page(tmp_path / "test.db")
        labels = [str(ta.label or "") for ta in at.text_area]
        assert not any("JD" in lb for lb in labels), (
            f"专项练习页不应要求 JD,实际: {labels}"
        )


class TestPracticeStart:
    def test_button_disabled_when_topic_empty(self, tmp_path: Path):
        at = _practice_page(tmp_path / "test.db")
        btn = _button_by_label(at, "启动专项练习")
        assert btn is not None
        assert btn.disabled is True, "主题为空时应 disabled"

    def test_start_sets_practice_state(self, tmp_path: Path):
        at = _practice_page(tmp_path / "test.db")
        at.session_state["mock_responses"] = ["kafka 的 ISR 怎么保证不丢消息?"]
        at.text_input(key="practice_topic_input").set_value("kafka 高可用")
        at.run()
        btn = _button_by_label(at, "启动专项练习")
        assert btn.disabled is False, "填了主题后按钮应可点"
        btn.click().run()

        assert at.session_state["practice_mode"] is True
        assert at.session_state["practice_topic"] == "kafka 高可用"
        assert at.session_state["viewing_history"] is False
        assert at.session_state["loaded_session_id"] == ""

    def test_start_works_without_jd(self, tmp_path: Path):
        """空 JD 也能启动,不该落 JD 报错。"""
        at = _practice_page(tmp_path / "test.db")
        at.session_state["jd_content"] = ""
        at.session_state["mock_responses"] = ["先讲讲 kafka 分区副本的作用?"]
        at.run()
        at.text_input(key="practice_topic_input").set_value("kafka 高可用")
        at.run()
        _button_by_label(at, "启动专项练习").click().run()

        assert at.session_state["practice_mode"] is True
        assert "JD" not in str(at.session_state["error_msg"])

    def test_topic_is_stripped(self, tmp_path: Path):
        at = _practice_page(tmp_path / "test.db")
        at.session_state["mock_responses"] = ["Redis 缓存击穿怎么防?"]
        at.text_input(key="practice_topic_input").set_value("  Redis 缓存击穿  ")
        at.run()
        _button_by_label(at, "启动专项练习").click().run()
        assert at.session_state["practice_topic"] == "Redis 缓存击穿"


class TestPracticePageInNav:
    def test_practice_in_page_paths(self):
        from interview_helpers import PAGE_PATHS
        assert PAGE_PATHS["practice"] == "pages/practice.py"

    def test_practice_page_file_exists(self):
        assert Path("pages/practice.py").exists()
