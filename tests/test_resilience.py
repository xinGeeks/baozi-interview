"""LLMError 子类 + 异常分类 + sys.excepthook + error.log 测试。"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from openai import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    PermissionDeniedError,
    RateLimitError,
)

from llm import (
    AuthError,
    LLMError,
    RateLimitError_,
    TransientError,
    UnknownError,
    _classify_sdk_exception,
)
import app as app_module
from app import _install_global_error_handler


def _make_response(status_code: int = 401) -> MagicMock:
    """构造 httpx.Response 替身(openai 异常构造时要求)。"""
    resp = MagicMock()
    resp.status_code = status_code
    resp.headers = {}
    return resp


# ============================================================================
# _classify_sdk_exception — 4 类映射
# ============================================================================


class TestClassifySDK:
    def test_authentication_error(self):
        e = AuthenticationError(
            message="Invalid API key",
            response=_make_response(401),
            body=None,
        )
        out = _classify_sdk_exception(e)
        assert isinstance(out, AuthError)

    def test_permission_denied(self):
        e = PermissionDeniedError(
            message="Forbidden",
            response=_make_response(403),
            body=None,
        )
        out = _classify_sdk_exception(e)
        assert isinstance(out, AuthError)

    def test_rate_limit_error(self):
        e = RateLimitError(
            message="Rate limit",
            response=_make_response(429),
            body=None,
        )
        out = _classify_sdk_exception(e)
        assert isinstance(out, RateLimitError_)

    def test_connection_error(self):
        e = APIConnectionError(request=MagicMock())
        out = _classify_sdk_exception(e)
        assert isinstance(out, TransientError)

    def test_timeout_error(self):
        e = APITimeoutError(request=MagicMock())
        out = _classify_sdk_exception(e)
        assert isinstance(out, TransientError)

    def test_value_error_unknown(self):
        out = _classify_sdk_exception(ValueError("some bug"))
        assert isinstance(out, UnknownError)

    def test_all_subclasses_inherit_llmerror(self):
        """AuthError / RateLimitError_ / TransientError / UnknownError 都应是 LLMError 子类。"""
        for cls in (AuthError, RateLimitError_, TransientError, UnknownError):
            assert issubclass(cls, LLMError)


# ============================================================================
# sys.excepthook + data/error.log
# ============================================================================


class TestGlobalErrorHandler:
    def test_install_registers_hook(self):
        original = sys.excepthook
        _install_global_error_handler()
        assert sys.excepthook is not original
        sys.excepthook = original  # 恢复

    def test_hook_writes_to_log(self, tmp_path: Path, monkeypatch):
        log_dir = tmp_path / "data"
        log_dir.mkdir()
        log_file = log_dir / "error.log"

        # monkeypatch 路径(interview_helpers._ERROR_LOG_PATH)
        import interview_helpers
        monkeypatch.setattr(interview_helpers, "_ERROR_LOG_PATH", log_file)

        _install_global_error_handler()
        # 模拟未捕获异常
        try:
            raise ValueError("test exception for log")
        except ValueError:
            sys.excepthook(*sys.exc_info())

        # log 应被写入
        assert log_file.exists()
        content = log_file.read_text(encoding="utf-8")
        assert "ValueError" in content
        assert "test exception for log" in content

    def test_hook_skips_keyboard_interrupt(self, tmp_path: Path, monkeypatch):
        """Ctrl+C 不写 error.log(用户主动终止,非 bug)。"""
        log_file = tmp_path / "error.log"
        import interview_helpers
        monkeypatch.setattr(interview_helpers, "_ERROR_LOG_PATH", log_file)

        # stub sys.__excepthook
        called = {"n": 0}
        def _stub(exc_type, exc_value, exc_tb):
            called["n"] += 1
        monkeypatch.setattr(sys, "__excepthook__", _stub)

        _install_global_error_handler()
        try:
            raise KeyboardInterrupt("user pressed ctrl+c")
        except KeyboardInterrupt:
            sys.excepthook(*sys.exc_info())

        # log 不应写
        assert not log_file.exists()
        # 但 __excepthook 仍被调
        assert called["n"] == 1
