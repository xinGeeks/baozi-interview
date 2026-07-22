"""llm.py 单测:chat() 非流式路径 + chat_stream() 流式路径(v0.3 Feature C)。

mock 策略:monkeypatch llm.make_client 返回可控 fake client,不走真实 SDK。
"""
from __future__ import annotations

from typing import Iterator

import pytest

from llm import LLMError, chat, chat_stream


# ============================================================================
# 假 SDK 数据结构
# ============================================================================

class _Delta:
    def __init__(self, content):
        self.content = content


class _Choice:
    def __init__(self, content):
        self.delta = _Delta(content)


class _Chunk:
    """模拟 openai 流式响应的单 chunk(streaming 时使用)。"""
    def __init__(self, content):
        self.choices = [_Choice(content)]


class _Message:
    def __init__(self, content):
        self.content = content


class _ChoiceMsg:
    def __init__(self, content):
        self.message = _Message(content)


class _FullResponse:
    """模拟非流式响应的完整 res 对象。"""
    def __init__(self, text):
        self.choices = [_ChoiceMsg(text)]


class _Completions:
    def __init__(self, *, chunks=None, full_text=None, stream_factory=None):
        self._chunks = chunks
        self._full_text = full_text
        self._stream_factory = stream_factory
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self._stream_factory is not None:
            return self._stream_factory()
        if self._chunks is not None:
            return iter(_Chunk(c) if c is not None else _Chunk("") for c in self._chunks)
        if self._full_text is not None:
            return _FullResponse(self._full_text)
        raise RuntimeError("FakeCompletions 未配置任何响应")


class _ChatNamespace:
    def __init__(self, completions):
        self.completions = completions


class _FakeClient:
    def __init__(self, *, chunks=None, full_text=None, stream_factory=None):
        self.chat = _ChatNamespace(
            _Completions(chunks=chunks, full_text=full_text, stream_factory=stream_factory)
        )


# ============================================================================
# fixtures
# ============================================================================

@pytest.fixture
def monkey_make_client(monkeypatch):
    """返回工厂:测试调用 fake(full_text=..., chunks=...) 改 fake 配置。

    设计:make_client 始终返回同一实例,_Completions.calls 是真正的 call 记录。
    测试可用 fake.client.chat.completions.calls 断言 SDK 参数(stream/temperature 等)。
    """
    state: dict = {"chunks": None, "full_text": None, "stream_factory": None}
    shared = {"client": None}

    def _build_client(cfg=None):
        client = _FakeClient(
            chunks=state["chunks"],
            full_text=state["full_text"],
            stream_factory=state["stream_factory"],
        )
        shared["client"] = client
        return client

    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    monkeypatch.setattr("llm.make_client", _build_client)

    class _FakeHandle:
        def __call__(self, *, chunks=None, full_text=None, stream_factory=None):
            state["chunks"] = chunks
            state["full_text"] = full_text
            state["stream_factory"] = stream_factory

        @property
        def client(self):
            return shared["client"]
    return _FakeHandle()


@pytest.fixture
def fake(monkey_make_client):
    """暴露给测试的 fake 句柄。"""
    return monkey_make_client


# ============================================================================
# chat() 非流式(回归 — 新增 chat_stream 不能影响旧路径)
# ============================================================================

def test_chat_returns_full_text(fake):
    """非流式返回完整字符串,不传 stream=True。"""
    fake(full_text="你好候选人")
    result = chat([{"role": "user", "content": "开场"}])
    assert result == "你好候选人"


def test_chat_does_not_pass_stream_flag(fake):
    """chat() 调用 completions.create() 时不传 stream=True(stream 默认 False)。"""
    fake(full_text="x")
    chat([{"role": "user", "content": "hi"}])
    compl = fake.client.chat.completions
    assert compl.calls[0].get("stream", False) is False


def test_chat_wraps_sdk_error(fake):
    """SDK 异常 → LLMError。"""
    def _boom():
        raise RuntimeError("连接超时")
    fake(stream_factory=_boom)
    with pytest.raises(LLMError) as exc_info:
        list(chat_stream([{"role": "user", "content": "hi"}]))
    assert "LLM" in str(exc_info.value)


# ============================================================================
# chat_stream()
# ============================================================================

def test_chat_stream_yields_incremental_pieces(fake):
    """三块增量文本,按顺序 yield。"""
    fake(chunks=["你", "好", "\n请问你的项目..."])
    pieces = list(chat_stream([{"role": "user", "content": "hi"}]))
    assert pieces == ["你", "好", "\n请问你的项目..."]


def test_chat_stream_passes_stream_true(fake):
    """stream=True 时确实把 stream=True 传给 SDK。"""
    fake(chunks=["a"])
    list(chat_stream([{"role": "user", "content": "hi"}]))
    compl = fake.client.chat.completions
    assert compl.calls[0].get("stream") is True


def test_chat_stream_skips_none_and_empty_content(fake):
    """delta.content 为 None 或 "" 时跳过。"""
    fake(chunks=["你", None, "好", "", "！"])
    pieces = list(chat_stream([{"role": "user", "content": "hi"}]))
    assert pieces == ["你", "好", "！"]


def test_chat_stream_compatible_with_concat_pattern(fake):
    """app.py 的累加器模式:"".join(pieces) = 完整响应。"""
    fake(chunks=["你好", "候选", "人,请", "介绍你自己。"])
    pieces = list(chat_stream([{"role": "user", "content": "hi"}]))
    assert "".join(pieces) == "你好候选人,请介绍你自己。"


def test_chat_stream_mid_stream_error_wrapped(fake):
    """流中途抛 → 已 yield 的片段交给调用方,异常 → LLMError。"""
    def _mid_boom():
        def gen():
            yield _Chunk("part1 ")
            raise RuntimeError("流中途断")
        return gen()
    fake(stream_factory=_mid_boom)

    pieces: list[str] = []
    with pytest.raises(LLMError) as exc_info:
        for chunk in chat_stream([{"role": "user", "content": "hi"}]):
            pieces.append(chunk)

    # 已经 yield 的部分留在调用方
    assert pieces == ["part1 "]
    assert "流中断" in str(exc_info.value) or "LLM" in str(exc_info.value)


def test_chat_stream_takes_temperature(fake):
    """temperature 参数透传给 SDK。"""
    fake(chunks=["x"])
    list(chat_stream([{"role": "user", "content": "hi"}], temperature=0.3))
    compl = fake.client.chat.completions
    assert compl.calls[0]["temperature"] == 0.3


def test_chat_stream_empty_response_yields_nothing(fake):
    """LLM 返回的空响应(全是 None)→ generator 0 块,不抛错。"""
    fake(chunks=[None, None, None])
    pieces = list(chat_stream([{"role": "user", "content": "hi"}]))
    assert pieces == []
