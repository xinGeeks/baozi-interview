"""app.py 入口集成测试 (Streamlit AppTest)。

覆盖 v0.3 multipage-navigation 拆页后 entry 的剩余职责:
- 全局 sidebar:清空全部历史 expander
- st.navigation 声明 4 页(default=config)

ToS 系统已移除(2026-07),此处不再覆盖 ToS 闸门相关行为。
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from storage import init_db


# ============================================================================
# 工具
# ============================================================================


def _entry(db_path: Path) -> AppTest:
    """构造指向 entry 的 AppTest,绑独立 DB。"""
    os.environ["STORAGE_DB_PATH"] = str(db_path)
    init_db(db_path)
    at = AppTest.from_file("app.py", default_timeout=10)
    at.run()
    return at


def _button_by_label(at: AppTest, needle: str):
    for b in at.button:
        if needle in str(b.label or ""):
            return b
    return None


# ============================================================================
# 全局 sidebar
# ============================================================================


class TestGlobalSidebar:
    def test_bulk_clear_expander_present(self, tmp_path: Path):
        """sidebar 应有『🗑️ 清空我的全部历史』expander。"""
        db = tmp_path / "test.db"
        at = _entry(db)
        expanders = [e for e in at.sidebar.expander if "清空" in str(e.label or "")]
        assert len(expanders) == 1, (
            f"期望 1 个清空历史 expander,实际: "
            f"{[(e.label or '') for e in at.sidebar.expander]}"
        )

    def test_bulk_clear_button_disabled_until_confirm(self, tmp_path: Path):
        """清空按钮在未输入『确认删除』时应 disabled。"""
        db = tmp_path / "test.db"
        at = _entry(db)
        clear_btn = _button_by_label(at, "清空全部历史")
        assert clear_btn is not None
        assert clear_btn.disabled is True, (
            "未输入确认文本时,清空按钮应 disabled"
        )


# ============================================================================
# navigation 声明
# ============================================================================


class TestNavigation:
    def test_default_page_is_config(self, tmp_path: Path):
        """默认 page 应为 config(检查 current_page 默认值)。"""
        from interview_helpers import DEFAULTS
        assert DEFAULTS["current_page"] == "config", (
            "DEFAULTS 应默认 current_page='config'"
        )

    def test_page_paths_dict_has_four_pages(self):
        """PAGE_PATHS 应声明 4 页。"""
        from interview_helpers import PAGE_PATHS
        assert set(PAGE_PATHS.keys()) == {
            "config", "interview", "report", "topics",
        }, f"PAGE_PATHS keys 应恰好 4 项,实际: {list(PAGE_PATHS.keys())}"

    def test_no_page_specific_render_in_entry(self, tmp_path: Path):
        """entry 不应残留 page-specific 渲染(标题不应是『面试对话』/『训练图谱』等)。"""
        db = tmp_path / "test.db"
        at = _entry(db)
        titles = [t.value for t in at.title]
        # 应是 config 标题,不是 interview/topics/report 标题
        assert any("配置面试" in t for t in titles)
        assert not any(
            kw in t for t in titles
            for kw in ("面试对话", "面试复盘报告", "训练图谱")
        ), f"entry 不应渲染 page-specific 标题,实际: {titles}"


# ============================================================================
# DB 初始化 + 异常 hook
# ============================================================================


class TestEntryBootstrap:
    def test_db_initialized_on_startup(self, tmp_path: Path):
        """entry 启动应初始化 DB(创建 interview_sessions 等表)。"""
        db = tmp_path / "test.db"
        os.environ["STORAGE_DB_PATH"] = str(db)
        at = AppTest.from_file("app.py", default_timeout=10)
        at.run()

        assert db.exists()
        with sqlite3.connect(str(db)) as conn:
            tables = {
                r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        assert "interview_sessions" in tables
        assert "interview_autosave" in tables

    def test_app_starts_without_exception(self, tmp_path: Path):
        """entry 启动不应抛异常。"""
        db = tmp_path / "test.db"
        at = _entry(db)
        assert not at.exception, f"entry 启动异常: {list(at.exception)}"