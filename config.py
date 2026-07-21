"""LLM 配置加载。

从环境变量读取 API key / endpoint / model,默认指向 MiniMax-M3。
.env 文件如果存在会被自动加载(无需 dotenv 依赖,仅做 KEY=VALUE 解析)。
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


DEFAULT_BASE_URL = "https://api.MiniMax.chat/v1"
DEFAULT_MODEL = "MiniMax-M3"


@dataclass(frozen=True)
class LLMConfig:
    api_key: str
    base_url: str
    model: str

    def is_configured(self) -> bool:
        return bool(self.api_key)


def _load_dotenv(path: Path) -> None:
    """极简 .env 加载:仅解析 KEY=VALUE 行,忽略注释/空行/引号。

    不引入 python-dotenv 依赖,只覆盖当前未设置的 env var。
    """
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def get_llm_config() -> LLMConfig:
    """读取 LLM 配置,优先环境变量,其次 .env 文件,最后用默认值。"""
    _load_dotenv(Path(__file__).parent / ".env")
    return LLMConfig(
        api_key=os.environ.get("LLM_API_KEY", ""),
        base_url=os.environ.get("LLM_BASE_URL", DEFAULT_BASE_URL),
        model=os.environ.get("LLM_MODEL", DEFAULT_MODEL),
    )
