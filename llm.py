"""LLM 调用的薄封装。

把 OpenAI SDK 调用集中在一处,主应用不直接依赖 SDK,方便测试时 monkeypatch。

v0.3 alpha-kickoff: LLMError 拆 4 子类,主应用按子类给不同提示。
"""
from __future__ import annotations

from typing import Iterable, Iterator

from openai import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    OpenAI,
    PermissionDeniedError,
    RateLimitError,
)

from config import LLMConfig, get_llm_config


class LLMError(Exception):
    """LLM 调用失败(基类)。"""


class AuthError(LLMError):
    """鉴权失败(API key 错 / 无权限 / 平台余额不足)。"""


class RateLimitError_(LLMError):
    """请求过快 / 触发限流。"""


class TransientError(LLMError):
    """临时性错误(网络抖动 / 服务端 5xx / 超时)。通常可重试。"""


class UnknownError(LLMError):
    """未归类异常(兜底)。"""


# 注:RateLimitError_ 下划线避免与 openai.RateLimitError 冲突


def _classify_sdk_exception(e: Exception) -> LLMError:
    """把 openai SDK 异常归到 4 个 LLMError 子类。"""
    msg = f"{type(e).__name__}: {e}"
    if isinstance(e, (AuthenticationError, PermissionDeniedError)):
        return AuthError(f"API key 无效或权限不足:{msg}")
    if isinstance(e, RateLimitError):
        return RateLimitError_(f"请求过快或触发限流:{msg}")
    if isinstance(e, (APIConnectionError, APITimeoutError)):
        return TransientError(f"网络不稳定或服务超时:{msg}")
    # openai 还可能抛 BadRequestError / InternalServerError 等
    name = type(e).__name__
    if "InternalServer" in name or "Server" in name:
        return TransientError(f"服务端错误:{msg}")
    return UnknownError(f"LLM 调用失败:{msg}")


def make_client(cfg: LLMConfig | None = None) -> OpenAI:
    """构造 OpenAI 兼容 client,默认从环境/.env 读配置。"""
    cfg = cfg or get_llm_config()
    if not cfg.is_configured():
        raise AuthError("未配置 LLM_API_KEY,请在 .env 或环境变量中设置")
    return OpenAI(api_key=cfg.api_key, base_url=cfg.base_url)


def chat(
    messages: Iterable[dict],
    *,
    cfg: LLMConfig | None = None,
    model: str | None = None,
    temperature: float = 0.7,
) -> str:  # noqa: D401
    """调一次 chat.completions,返回首个 choice 的 content 文本。"""
    cfg = cfg or get_llm_config()
    client = make_client(cfg)
    try:
        res = client.chat.completions.create(
            model=model or cfg.model,
            messages=list(messages),
            temperature=temperature,
        )
    except LLMError:
        raise
    except Exception as e:
        raise _classify_sdk_exception(e) from e

    try:
        return res.choices[0].message.content or ""
    except (AttributeError, IndexError) as e:
        raise UnknownError(f"LLM 响应格式异常:{e}") from e


def chat_stream(
    messages: Iterable[dict],
    *,
    cfg: LLMConfig | None = None,
    model: str | None = None,
    temperature: float = 0.7,
) -> Iterator[str]:
    """流式调一次 chat.completions(stream=True),逐块 yield 增量文本。"""
    cfg = cfg or get_llm_config()
    client = make_client(cfg)
    try:
        stream = client.chat.completions.create(
            model=model or cfg.model,
            messages=list(messages),
            temperature=temperature,
            stream=True,
        )
    except LLMError:
        raise
    except Exception as e:
        raise _classify_sdk_exception(e) from e

    try:
        for chunk in stream:
            piece = chunk.choices[0].delta.content
            if piece:
                yield piece
    except Exception as e:
        raise TransientError(f"LLM 流中断:{type(e).__name__}: {e}") from e
