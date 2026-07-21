"""共享 pytest fixtures。

- configure_llm:为 app.py 配置 LLM_API_KEY(避免因 API key 缺失导致所有 LLM 路径报错)
- fake_llm_factory:为需要响应序列的测试构造 fake LLM

注意:`app.py` 用 `from llm import chat`,所以 monkeypatch 必须 patch `app.chat`
而不是 `llm.chat`,否则换不掉模块级绑定。
"""
from __future__ import annotations

import pytest


@pytest.fixture
def configure_llm(monkeypatch):
    """保证 app.chat() 不会因缺 API key 抛 LLMError。"""
    monkeypatch.setenv("LLM_API_KEY", "sk-test-fixture-key")


class FakeLLM:
    """按调用次数返回预置内容;无响应时返回哨兵。"""

    def __init__(self, responses: list[str]):
        self.responses = list(responses)
        self.calls: list[list[dict]] = []

    def __call__(self, messages, **kwargs):
        self.calls.append(list(messages))
        if not self.responses:
            return "[FAKE: NO MORE RESPONSES]"
        return self.responses.pop(0)


@pytest.fixture
def fake_llm():
    """返回 FakeLLM 实例,测试自己负责 monkeypatch 到 app.chat。"""
    return FakeLLM
