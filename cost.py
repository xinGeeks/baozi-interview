"""LLM 成本控制(估算口径)。

设计原则:
- char/4 估算,无新依赖(无 tiktoken);±25% 误差已文档化
- 内存计数 + UTC 日切,持久化依赖 st.session_state
- 不修改 llm.py 接口;只暴露 estimate + counter,UI 自行决策
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


# 软警告 / 硬熔断阈值(占 cap 的百分比)
WARNING_RATIO = 0.80
BLOCK_RATIO = 1.00


def estimate_tokens(text: str) -> int:
    """估算 token 数:char // 4(CJK / 英文 / 数字混合场景 ±25%)。

    零长字符串 → 0。
    """
    if not text:
        return 0
    return max(1, len(text) // 4)


def estimate_messages_tokens(messages: list[dict]) -> int:
    """估算一组 chat messages 的 token 总数(每条 content + 4 字符 role 头)。"""
    if not messages:
        return 0
    total = 0
    for m in messages:
        content = str(m.get("content", ""))
        # role 头约 4 char,每条消息再加 4 字符"包装"
        total += estimate_tokens(content) + 2
    return total


@dataclass
class DailyTokenCounter:
    """内存态 token 计数器(按 UTC 日切)。

    用法:
        c = DailyTokenCounter(cap=200_000)
        c.add(1500)
        c.add(800)         # 跨日会自动重置
        c.current          # 2300 或重置后的值
        c.is_warning       # True if current >= 80% cap
        c.is_blocked       # True if current >= 100% cap
        c.percent          # 0.0 ~ 1.0+(>1 表示超 cap)
    """
    cap: int = 0
    current: int = 0
    last_reset_utc_date: str = field(
        default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%d")
    )

    def _maybe_reset(self) -> None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if today != self.last_reset_utc_date:
            self.current = 0
            self.last_reset_utc_date = today

    def add(self, n: int) -> int:
        """累加 n 个 token(可能为 0 / 负数视为 0)。返回累加后当前值。"""
        if n <= 0:
            return self.current
        self._maybe_reset()
        self.current += n
        return self.current

    def reset(self) -> None:
        """手动重置(测试用 + 用户调高 cap 后想重置累计时)。"""
        self.current = 0
        self.last_reset_utc_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    @property
    def is_warning(self) -> bool:
        if self.cap <= 0:
            return False
        return self.current >= self.cap * WARNING_RATIO

    @property
    def is_blocked(self) -> bool:
        if self.cap <= 0:
            return False
        return self.current >= self.cap * BLOCK_RATIO

    @property
    def percent(self) -> float:
        if self.cap <= 0:
            return 0.0
        return self.current / self.cap
