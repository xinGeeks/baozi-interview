"""真实性检测 (Authenticity Detection)

per-turn 启发式 (detect_signals) + report-time LLM 聚合
(build_authenticity_judgment_prompt / parse_authenticity_response)。

设计原则:
- 零 LLM 成本 per turn:启发式 <1ms
- 报告时单次 LLM 聚合:沿用现有 _do_chat 路径
- 输出向后兼容:所有 Optional,旧调用点零改动
- 不修改分数:flag-only,UI 显示 ⚠️ 自查

v0.3 Feature E,见 openspec/changes/add-authenticity-detection/。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field


# ============================================================================
# 常量
# ============================================================================

SIGNAL_VOCAB: tuple[str, ...] = (
    "过于简短",
    "模板化",
    "答非所问",
    "未引用简历",
)

GENERIC_PHRASES: tuple[str, ...] = (
    "很多东西",
    "很多项目",
    "比较熟悉",
    "比较了解",
    "有所了解",
    "负责过",
    "使用过",
    "学习过",
)

STOPWORDS_CN: frozenset[str] = frozenset({
    "的", "了", "和", "是", "在", "我", "你", "他", "她", "它", "们",
    "有", "没", "这", "那", "就", "也", "都", "还", "但", "而", "或",
    "把", "被", "给", "向", "从", "对", "以", "为", "到", "跟",
    "能", "会", "可以", "应该", "可能", "需要", "想", "让", "使",
    "做", "说", "看", "想", "知道", "觉得", "认为", "感觉",
    "什么", "怎么", "为什么", "哪些", "哪个", "多少", "几个",
    "一个", "一些", "这个", "那个", "这些", "那些",
    "啊", "吧", "呢", "哦", "嗯", "哈", "哎", "呀", "哇",
    "吗", "嘛", "啦", "咯", "呵", "嘿",
    "、", "。", "？", "！", "，", "；", "：", """, """, "'", "'",
    "（", "）", "【", "】", "《", "》",
})

STOPWORDS_EN: frozenset[str] = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "i", "you", "he", "she", "it", "we", "they", "them", "their",
    "and", "or", "but", "so", "if", "then",
    "to", "of", "in", "on", "at", "for", "with", "by", "from",
    "this", "that", "these", "those",
    "do", "does", "did", "doing",
    "have", "has", "had",
})

_MIN_ANSWER_WORDS = 8
_Q_OVERLAP_THRESHOLD = 0.15
_TOP_RESUME_ENTITIES = 30

_TOKEN_RE = re.compile(r"[一-鿿]+|[A-Za-z]+|[0-9]+")


def _is_cjk(ch: str) -> bool:
    return "一" <= ch <= "鿿"


# ============================================================================
# 文本处理 helpers
# ============================================================================


def _content_tokens(text: str) -> set[str]:
    """2-gram sliding windows for CJK + whole English/digit words。

    设计:中文没有空格分词,整段"我做了订单系统"会被 regex 当一个 token,
    完全无法做 keyword overlap。改用 2-gram(CJK run 内每个相邻 2 字一组),
    再过滤掉含停用字的 bigram(如"做了"、"的订")。

    英文 / 数字单词保留整词(长度 ≥2 才算 content)。
    """
    out: set[str] = set()
    for m in _TOKEN_RE.finditer(text):
        tok = m.group().lower()
        if not tok or tok in STOPWORDS_CN or tok in STOPWORDS_EN:
            continue
        if all(_is_cjk(c) for c in tok):
            for i in range(len(tok) - 1):
                bg = tok[i:i + 2]
                if bg[0] in STOPWORDS_CN or bg[1] in STOPWORDS_CN:
                    continue
                out.add(bg)
        elif len(tok) >= 2:
            out.add(tok)
    return out


def _resume_entities(resume_text: str, top_n: int = _TOP_RESUME_ENTITIES) -> set[str]:
    """从简历提取 top-N 高频 2-gram 当作"实体代理"。

    简历里高频出现的 2-gram 大概率是项目名 / 技术栈 / 公司名片段。
    不追求完美:启发式只起粗筛作用,false negative 可接受。
    """
    if not resume_text or not resume_text.strip():
        return set()
    counts: dict[str, int] = {}
    for m in _TOKEN_RE.finditer(resume_text):
        tok = m.group().lower()
        if not tok or tok in STOPWORDS_CN or tok in STOPWORDS_EN:
            continue
        if all(_is_cjk(c) for c in tok):
            for i in range(len(tok) - 1):
                bg = tok[i:i + 2]
                if bg[0] in STOPWORDS_CN or bg[1] in STOPWORDS_CN:
                    continue
                counts[bg] = counts.get(bg, 0) + 1
        elif len(tok) >= 2:
            counts[tok] = counts.get(tok, 0) + 1
    top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:top_n]
    return {t for t, _ in top}


def _mentions_any_entity(answer: str, entities: set[str]) -> bool:
    """答案是否提及简历里任一实体(substring 匹配)。

    空 entities → True(无法判断时放过,避免误伤无简历用户)。

    用 substring 而非 token 重叠:中文里"订单系统"作为 substring 出现在
    "我做了订单系统重构"里,token 重叠要求 token 完全相等不实用。
    """
    if not entities:
        return True
    a_lower = answer.lower()
    return any(e in a_lower for e in entities)


# ============================================================================
# 启发式 per-turn 检测
# ============================================================================


def detect_signals(
    question: str,
    answer: str,
    resume_text: str = "",
) -> list[str]:
    """per-turn 真实性信号检测(零 LLM 成本,<1ms/200 词)。

    4 条规则,顺序执行,短路返回。所有规则共用 _tokenize 结果。

    Args:
        question: 面试官问题
        answer: 候选人回答
        resume_text: 候选人简历(可空)

    Returns:
        SIGNAL_VOCAB 子集(可能为空)。
    """
    if not answer or not answer.strip():
        return ["过于简短"]

    flags: list[str] = []
    n_words = len(answer.split())

    if n_words < _MIN_ANSWER_WORDS and "?" not in answer and "？" not in answer:
        flags.append("过于简短")

    has_generic = any(g in answer for g in GENERIC_PHRASES)
    has_digit = any(c.isdigit() for c in answer)
    if has_generic and not has_digit:
        flags.append("模板化")

    q_tokens = _content_tokens(question)
    a_tokens = _content_tokens(answer)
    if q_tokens:
        overlap = len(q_tokens & a_tokens) / len(q_tokens)
        if overlap < _Q_OVERLAP_THRESHOLD:
            flags.append("答非所问")

    entities = _resume_entities(resume_text)
    if entities and not _mentions_any_entity(answer, entities):
        flags.append("未引用简历")

    return flags


# ============================================================================
# Report-time LLM 聚合
# ============================================================================


@dataclass
class Finding:
    turn: int
    issue: str
    detail: str


@dataclass
class AuthenticityReport:
    score: float  # -1.0 sentinel 表示 parse 失败
    findings: list[Finding] = field(default_factory=list)
    summary: str = ""

    @property
    def is_valid(self) -> bool:
        return self.score >= 0


_HARD_CONSTRAINT = (
    "【硬约束】只基于 given signals 推断,不得编造未在 signals 中出现的"
    "事实;若 signals 全为空,score 必须是 1.0 且 findings 必须是空列表。"
    "findings 最多 3 条,每条 detail ≤ 40 字。"
)

_JSON_FORMAT = (
    "严格 JSON 输出(无 markdown 包装,无 ```json 围栏):\n"
    '{"score": 0.0~1.0, "findings": [{"turn": N, "issue": "...", "detail": "..."}], "summary": "..."}'
)


def build_authenticity_judgment_prompt(
    resume: str,
    jd: str,
    chat_history: list[dict],
    turn_flags: list[list[str]],
) -> str:
    """构造 LLM 聚合 prompt(报告生成末尾调一次)。"""
    transcript = "\n".join(
        f"[{'面试官' if m['role'] == 'assistant' else '候选人'}]: {m['content']}"
        for m in chat_history
    )
    user_turns = [m for m in chat_history if m["role"] == "user"]
    flag_lines = []
    for i, (turn, flags) in enumerate(zip(user_turns, turn_flags), 1):
        if flags:
            flag_lines.append(
                f"- 轮 {i}({turn['content'][:30]}...): {' / '.join(flags)}"
            )
    flag_section = "\n".join(flag_lines) if flag_lines else "(无信号)"

    return f"""你是面试官助理,基于以下面试记录 + 给定的启发式 signals,评估候选人回答的真实性。

【简历】:
{resume.strip() or "(未上传)"}

【JD】:
{jd.strip() or "(未填写)"}

【完整对话】:
{transcript}

【启发式 signals(per-turn)】:
{flag_section}

{_HARD_CONSTRAINT}

{_JSON_FORMAT}
"""


def parse_authenticity_response(text: str) -> AuthenticityReport:
    """容错解析 LLM 输出。失败 → 返回 sentinel(score=-1)。

    容错策略:
    - 剥 <think> 块
    - 找首个平衡 JSON
    - 缺字段 → sentinel
    - score 越界 → 截 [0, 1]
    - findings > 3 → 截断到 3
    - summary > 200 字 → 截断
    """
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

    start = text.find("{")
    if start < 0:
        return AuthenticityReport(score=-1.0, summary="LLM 解析失败:无 JSON")
    depth = 0
    end = -1
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end < 0:
        return AuthenticityReport(score=-1.0, summary="LLM 解析失败:JSON 不闭合")

    try:
        data = json.loads(text[start:end])
    except json.JSONDecodeError as e:
        return AuthenticityReport(score=-1.0, summary=f"LLM 解析失败:{e}")

    # score: 缺字段 → sentinel;给了就截 [0, 1](含负数截 0)
    if "score" not in data:
        score = -1.0
    else:
        try:
            score = float(data.get("score"))
        except (TypeError, ValueError):
            score = -1.0
        if score >= 0:
            score = max(0.0, min(1.0, score))
        else:
            score = 0.0  # 负数 clamp 到 0,不算 parse 失败

    raw_findings = data.get("findings", []) or []
    if not isinstance(raw_findings, list):
        raw_findings = []
    findings: list[Finding] = []
    for f in raw_findings:
        if not isinstance(f, dict):
            continue
        try:
            turn = int(f.get("turn", 0))
        except (TypeError, ValueError):
            turn = 0
        issue = str(f.get("issue", "")).strip()[:40]
        detail = str(f.get("detail", "")).strip()[:40]
        if issue or detail:
            findings.append(Finding(turn=turn, issue=issue, detail=detail))
    findings = findings[:3]  # 过滤后再截断,避免截掉合法 dict

    summary = str(data.get("summary", "")).strip()[:200]

    return AuthenticityReport(score=score, findings=findings, summary=summary)