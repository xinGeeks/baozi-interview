"""consent_log + ToS 流程测试。

- record_consent / has_accepted_tos:Storage 单元
- ToS modal 渲染:AppTest 集成
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from storage import (
    get_candidate_id,
    has_accepted_tos,
    init_db,
    record_consent,
)


# ============================================================================
# Storage 单元测试
# ============================================================================


class TestRecordConsent:
    def test_record_and_check_roundtrip(self, tmp_path: Path):
        db = tmp_path / "test.db"
        init_db(db)
        cid = get_candidate_id()
        assert has_accepted_tos(db, cid, "2026-07-22-v1") is False
        record_consent(db, cid, "2026-07-22-v1")
        assert has_accepted_tos(db, cid, "2026-07-22-v1") is True

    def test_re_record_same_version_idempotent(self, tmp_path: Path):
        """UNIQUE 约束 → 重复接受同一 version 不会报错。"""
        db = tmp_path / "test.db"
        init_db(db)
        cid = get_candidate_id()
        record_consent(db, cid, "v1")
        record_consent(db, cid, "v1")  # 不抛
        assert has_accepted_tos(db, cid, "v1") is True

    def test_different_versions_independent(self, tmp_path: Path):
        db = tmp_path / "test.db"
        init_db(db)
        cid = get_candidate_id()
        record_consent(db, cid, "v1")
        # 旧 version 仍被记录
        assert has_accepted_tos(db, cid, "v1") is True
        # 新 version 未接受
        assert has_accepted_tos(db, cid, "v2") is False

    def test_explicit_accepted_at_respected(self, tmp_path: Path):
        db = tmp_path / "test.db"
        init_db(db)
        ts = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        record_consent(db, get_candidate_id(), "v1", accepted_at=ts)
        assert has_accepted_tos(db, get_candidate_id(), "v1") is True


# ============================================================================
# ToS modal AppTest 集成
# ============================================================================


@pytest.fixture
def fresh_db_env(monkeypatch, tmp_path: Path):
    """每个测试用独立 DB,避免污染。"""
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("STORAGE_DB_PATH", str(db_path))
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    return db_path


class TestToSModal:
    def test_modal_blocks_interview_on_first_load(self, fresh_db_env):
        """未接受 ToS → 主区显示 modal,JD 粘贴区不渲染。"""
        at = AppTest.from_file("app.py").run()
        assert at.exception is None or len(at.exception) == 0
        # 标题存在(subheader + markdown 都可)
        subheaders = [s for s in at.subheader if "服务条款" in str(s.value)]
        assert len(subheaders) >= 1, (
            f"expected ToS subheader, got: {[s.value for s in at.subheader]}"
        )
        # JD 文本区不应可见(modal 在前面 st.stop)
        text_areas = [t for t in at.text_area if "JD" in str(t.label)]
        assert len(text_areas) == 0

    def test_accept_button_disabled_without_checkbox(self, fresh_db_env):
        at = AppTest.from_file("app.py").run()
        accept_btn = next(
            (b for b in at.button if "确认接受" in str(b.label)),
            None,
        )
        assert accept_btn is not None
        # 复选框未勾 → 按钮 disabled
        assert accept_btn.disabled is True

    def test_accept_checkbox_then_button_unlocks(self, fresh_db_env):
        at = AppTest.from_file("app.py").run()
        # 找到 ToS 复选框
        cb = next(
            (c for c in at.checkbox if "服务条款" in str(c.label)),
            None,
        )
        assert cb is not None
        cb.check()
        at.run()
        # 再 run 一次,按钮应启用
        accept_btn = next(
            (b for b in at.button if "确认接受" in str(b.label)),
            None,
        )
        assert accept_btn is not None
        assert accept_btn.disabled is False

    def test_accepted_state_persists_across_runs(self, fresh_db_env):
        """第一次接受后,rerun 不再显示 modal。"""
        at = AppTest.from_file("app.py").run()
        cb = next(c for c in at.checkbox if "服务条款" in str(c.label))
        cb.check()
        at.run()
        accept_btn = next(b for b in at.button if "确认接受" in str(b.label))
        accept_btn.click()
        at.run()
        # 第二次 run:modal 应消失,JD 区可见
        at2 = AppTest.from_file("app.py").run()
        # 不应再看到「服务条款」标题
        assert not any("服务条款" in str(m.value) for m in at2.markdown)
        # JD 文本区应可见
        text_areas = [t for t in at2.text_area if "JD" in str(t.label)]
        assert len(text_areas) == 1
