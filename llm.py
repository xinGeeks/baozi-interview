"""LLM 调用的薄封装。

把 OpenAI SDK 调用集中在一处,主应用不直接依赖 SDK,方便测试时 monkeypatch。
"""
from __future__ import annotations

from typing import Iterable

from openai import OpenAI

from config import LLMConfig, get_llm_config


class LLMError(Exception):
    """LLM 调用失败(网络/限流/鉴权/解析),主应用据此展示友好提示。"""


def make_client(cfg: LLMConfig | None = None) -> OpenAI:
    """构造 OpenAI 兼容 client,默认从环境/.env 读配置。"""
    cfg = cfg or get_llm_config()
    if not cfg.is_configured():
        raise LLMError("未配置 LLM_API_KEY,请在 .env 或环境变量中设置")
    return OpenAI(api_key=cfg.api_key, base_url=cfg.base_url)


def chat(
    messages: Iterable[dict],
    *,
    cfg: LLMConfig | None = None,
    model: str | None = None,
    temperature: float = 0.7,
) -> str:  # noqa: D401
    """调一次 chat.completions,返回首个 choice 的 content 文本。

    Args:
        messages: OpenAI 格式消息列表
        cfg: LLM 配置;None 时自动从 env 读
        model: 覆盖 cfg.model
        temperature: 采样温度
    """
    cfg = cfg or get_llm_config()
    client = make_client(cfg)
    try:
        res = client.chat.completions.create(
            model=model or cfg.model,
            messages=list(messages),
            temperature=temperature,
        )
    except Exception as e:  # 任何 SDK 异常统一封装,主应用只关心 LLMError
        raise LLMError(f"LLM 调用失败:{type(e).__name__}: {e}") from e

    try:
        return res.choices[0].message.content or ""
    except (AttributeError, IndexError) as e:
        raise LLMError(f"LLM 响应格式异常:{e}") from e
