"""config.py 单元测试。"""
import os
from pathlib import Path

import pytest

from config import DEFAULT_BASE_URL, DEFAULT_MODEL, LLMConfig, get_llm_config


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """每个测试清空 LLM_* 变量,避免宿主 env 污染。

    .env 加载不在此禁,因为有测试显式要测 .env 行为;
    测"默认值"的测试自己用 _no_dotenv fixture 显式禁。
    """
    for key in ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL"):
        monkeypatch.delenv(key, raising=False)
    yield


@pytest.fixture
def no_dotenv(monkeypatch):
    """禁用 .env 加载,用于测"完全无配置"场景。"""
    import config as _config_mod
    monkeypatch.setattr(_config_mod, "_load_dotenv", lambda path: None)


def test_get_llm_config_all_defaults(no_dotenv):
    cfg = get_llm_config()
    assert cfg.api_key == ""
    assert cfg.base_url == DEFAULT_BASE_URL
    assert cfg.model == DEFAULT_MODEL
    assert cfg.is_configured() is False


def test_get_llm_config_full_env(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-test-123")
    monkeypatch.setenv("LLM_BASE_URL", "https://custom.example.com/v1")
    monkeypatch.setenv("LLM_MODEL", "custom-model")
    cfg = get_llm_config()
    assert cfg.api_key == "sk-test-123"
    assert cfg.base_url == "https://custom.example.com/v1"
    assert cfg.model == "custom-model"
    assert cfg.is_configured() is True


def test_get_llm_config_partial_env(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-only-key")
    cfg = get_llm_config()
    assert cfg.api_key == "sk-only-key"
    assert cfg.base_url == DEFAULT_BASE_URL
    assert cfg.model == DEFAULT_MODEL


def test_get_llm_config_loads_dotenv(monkeypatch, tmp_path):
    """当 env var 未设置时,.env 文件应当生效;已设置的 env var 优先。"""
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "# comment\n"
        "\n"
        "LLM_API_KEY=from-dotenv\n"
        "LLM_BASE_URL=https://from-dotenv.example.com/v1\n"
        'LLM_MODEL="quoted-model"\n',
        encoding="utf-8",
    )

    # 模拟 config.py 中 _load_dotenv(tmp_path/.env) 的行为
    from config import _load_dotenv
    _load_dotenv(dotenv)

    cfg = get_llm_config()
    assert cfg.api_key == "from-dotenv"
    assert cfg.base_url == "https://from-dotenv.example.com/v1"
    assert cfg.model == "quoted-model"  # 引号被剥除


def test_load_dotenv_does_not_override_existing_env(monkeypatch, tmp_path):
    """已存在的 env var 不会被 .env 覆盖。"""
    monkeypatch.setenv("LLM_API_KEY", "from-env")
    dotenv = tmp_path / ".env"
    dotenv.write_text("LLM_API_KEY=from-dotenv\n", encoding="utf-8")

    from config import _load_dotenv
    _load_dotenv(dotenv)

    assert os.environ["LLM_API_KEY"] == "from-env"


def test_load_dotenv_handles_missing_file(tmp_path):
    """不存在的文件应静默跳过。"""
    from config import _load_dotenv
    _load_dotenv(tmp_path / "nope.env")  # 不应抛错


def test_load_dotenv_skips_blank_and_comments(tmp_path):
    dotenv = tmp_path / ".env"
    dotenv.write_text("\n# a comment\n\nLLM_API_KEY=x\n", encoding="utf-8")
    from config import _load_dotenv
    _load_dotenv(dotenv)
    assert os.environ["LLM_API_KEY"] == "x"


def test_llm_config_is_frozen():
    cfg = LLMConfig(api_key="x", base_url="y", model="z")
    with pytest.raises(Exception):  # FrozenInstanceError
        cfg.api_key = "w"  # type: ignore[misc]
