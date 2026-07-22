"""每轮即时反馈:prompt 构造 + 响应解析。

纯函数模块,无 IO。给 app.py 复用,不在这里做 LLM 调用。

输出格式约定(LLM 必须严格两行):
    【分数】N/10
    【建议】一句话(≤40 字)
"""
from __future__ import annotations

import re


THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
SCORE_RE = re.compile(r"【分数】\s*(-?\d+)\s*/\s*10")
ADVICE_RE = re.compile(r"【建议】\s*(.+?)(?:【|$)", re.DOTALL)


def build_feedback_prompt(level: str, question: str, answer: str) -> str:
    """构造单轮反馈 prompt。

    故意不传 resume / JD:评估的是候选人本轮回答本身的质量,
    而不是与 JD 的匹配度(那是报告段的事)。
    """
    return f"""你是一名面试教练,基于候选人本轮回答给 0-10 分 + 一句话改进建议。
你是教练,不是雇主;目标是帮候选人下次答得更好,不是给录用判决。

【面试等级】:{level}
【面试官问题】:{question}
【候选人回答】:{answer}

输出格式(严格两行,不得多行不得少行):
【分数】N/10
【建议】一句话(≤40 字,引用原话,指出最值得改的一点)

【反虚高锚定】(每个分数必须满足对应证据,否则向下取整):
- 5 分 = 默认:回答完整不跑题即给 5,代表『及格线』。大多数普通回答应落 4-6。
- 6 分 = 至少 1 个具体细节(数据 / 案例 / 类比)。
- 7 分 = 清晰逻辑结构(论点 + 论据 / STAR 完整)。
- 8 分 = 可量化的成果或独特洞察;罕见。
- 9 分 = 极罕见:创新思考、反例自纠、或跨领域迁移。
- 10 分 = 几乎不发,确实完美才发。
- ≤4 分 = 必须能指出具体扣分点(答非所问 / 编造 / 自相矛盾 / 空话)。

硬约束:
- 想给 7+ 必须能列出至少 1 条具体证据,否则扣到 5。
- 建议要具体(改什么、加什么数据、删什么废话)。
- 禁止『综合表现良好』『具有一定潜力』等套话。
"""


def parse_feedback_response(text: str) -> dict:
    """容错解析 LLM 输出,返回 {"score": int, "advice": str}。

    - 缺【分数】→ 兜底 5
    - 缺【建议】→ 兜底空串
    - 分数越界 → 截到 [0, 10]
    - 多行建议 → 取第一行
    - 含 <think> 块 → 先剥除
    """
    text = THINK_RE.sub("", text).strip()
    score_m = SCORE_RE.search(text)
    advice_m = ADVICE_RE.search(text)

    if score_m:
        score = max(0, min(10, int(score_m.group(1))))
    else:
        score = 5

    if advice_m:
        advice = advice_m.group(1).strip().split("\n")[0].strip()
    else:
        advice = ""

    return {"score": score, "advice": advice}