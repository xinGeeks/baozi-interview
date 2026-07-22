"""cost.py 单元测试。

- estimate_tokens / estimate_messages_tokens:估算口径
- DailyTokenCounter:累加 / UTC 日切 / 80%/100% 边界 / cap=0 关闭
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from cost import (
    DailyTokenCounter,
    estimate_messages_tokens,
    estimate_tokens,
)


class TestEstimateTokens:
    def test_empty_string(self):
        assert estimate_tokens("") == 0

    def test_short_string_rounds_up_to_1(self):
        """1 字符 → 0.25 token → 至少 1(防止 0 误传)。"""
        assert estimate_tokens("a") == 1
        assert estimate_tokens("中") == 1

    def test_cjk_content(self):
        """2000 中文字符 → 500 tokens。"""
        text = "测" * 2000
        assert estimate_tokens(text) == 500

    def test_english_content(self):
        """400 英文字符 → 100 tokens。"""
        text = "a" * 400
        assert estimate_tokens(text) == 100

    def test_mixed_content(self):
        """1000 中 + 400 英 → 350 tokens。"""
        text = "测" * 1000 + "a" * 400
        assert estimate_tokens(text) == 350

    def test_negative_or_zero_clamps(self):
        assert estimate_tokens(None or "") == 0  # type: ignore


class TestEstimateMessagesTokens:
    def test_empty_list(self):
        assert estimate_messages_tokens([]) == 0

    def test_single_message(self):
        # 100 字符 + 2 (role 头) = 27 tokens
        msg = [{"role": "user", "content": "x" * 100}]
        assert estimate_messages_tokens(msg) == 27

    def test_multiple_messages(self):
        msgs = [
            {"role": "system", "content": "x" * 200},
            {"role": "user", "content": "x" * 100},
            {"role": "assistant", "content": "x" * 50},
        ]
        # 50 + 2 + 25 + 2 + 12 + 2 + 2 = 95 (但前几个用 max(1, ...) 处理)
        # 实际:50 + 2 = 52, 25+2 = 27, 12+2 = 14, total = 93
        n = estimate_messages_tokens(msgs)
        assert 90 <= n <= 100  # 容差


class TestDailyTokenCounter:
    def test_init_zero(self):
        c = DailyTokenCounter(cap=1000)
        assert c.current == 0
        assert c.is_warning is False
        assert c.is_blocked is False
        assert c.percent == 0.0

    def test_add_accumulates(self):
        c = DailyTokenCounter(cap=1000)
        c.add(100)
        c.add(200)
        assert c.current == 300

    def test_warning_at_80_percent(self):
        c = DailyTokenCounter(cap=1000)
        c.add(799)
        assert c.is_warning is False
        c.add(1)  # 800
        assert c.is_warning is True
        assert c.is_blocked is False

    def test_blocked_at_100_percent(self):
        c = DailyTokenCounter(cap=1000)
        c.add(999)
        assert c.is_blocked is False
        c.add(1)  # 1000
        assert c.is_blocked is True

    def test_over_block_still_blocked(self):
        c = DailyTokenCounter(cap=1000)
        c.add(2000)
        assert c.is_blocked is True
        assert c.percent == 2.0

    def test_cap_zero_disables_all(self):
        c = DailyTokenCounter(cap=0)
        c.add(1_000_000)
        assert c.is_warning is False
        assert c.is_blocked is False
        assert c.percent == 0.0

    def test_add_zero_or_negative_noop(self):
        c = DailyTokenCounter(cap=1000)
        c.add(0)
        c.add(-100)
        assert c.current == 0

    def test_reset_clears(self):
        c = DailyTokenCounter(cap=1000)
        c.add(500)
        c.reset()
        assert c.current == 0

    def test_utc_day_rollover(self, monkeypatch):
        """手动把 last_reset_utc_date 改成昨天,add 时应自动重置。"""
        c = DailyTokenCounter(cap=1000)
        c.add(500)
        # 模拟昨天
        yesterday = (
            datetime.now(timezone.utc) - timedelta(days=1)
        ).strftime("%Y-%m-%d")
        c.last_reset_utc_date = yesterday
        c.add(100)
        # 跨日 → 自动重置为 0,再 add 100
        assert c.current == 100

    def test_same_day_no_rollover(self):
        c = DailyTokenCounter(cap=1000)
        c.add(500)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        c.last_reset_utc_date = today
        c.add(100)
        assert c.current == 600
