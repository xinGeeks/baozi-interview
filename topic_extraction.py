"""跨会话 topic 抽取 (Rule-based, 零 LLM)

CJK 2-gram sliding window + 同义词聚类 + PII mask + 阈值过滤,
从 interview turns 提取稳定的训练主题供 sidebar 折叠区可视化。

设计原则:
- 零 LLM 成本:session 末 inline 抽取,<500ms/30 turns
- 复用 authenticity.py 的 CJK tokenize 算法,保证两个视角一致
- PII 安全:mask 公司名 / 项目代号 / 通用敏感词在 tokenize 之前
- 双阈值过滤短会话噪声:min_tf=3 AND min_ratio=0.05
- TopicFact 不可变 dataclass,跨模块传递安全

v0.3 Feature F,见 openspec/changes/add-cross-session-topic-memory/。
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass


# ============================================================================
# TopicFact
# ============================================================================


@dataclass(frozen=True)
class TopicFact:
    """单个 session 内识别到的一个训练主题。

    score 归一化:tf / total_tokens,在 [0, 1] 范围。
    source_turn:turn 在 turns 列表中的索引(0-based)。
    """
    topic: str
    score: float
    source_turn: int


# ============================================================================
# 常量:Stopwords / PII / Synonyms
# ============================================================================


_STOPWORDS: frozenset[str] = frozenset({
    # 中文常用虚词 / 助词 / 代词
    "的", "了", "和", "是", "在", "我", "你", "他", "她", "它", "们",
    "有", "没", "这", "那", "就", "也", "都", "还", "但", "而", "或",
    "把", "被", "给", "向", "从", "对", "以", "为", "到", "跟",
    "能", "会", "可以", "应该", "可能", "需要", "想", "让", "使",
    "做", "说", "看", "知道", "觉得", "认为", "感觉",
    "什么", "怎么", "为什么", "哪些", "哪个", "多少", "几个",
    "一个", "一些", "这个", "那个", "这些", "那些",
    "啊", "吧", "呢", "哦", "嗯", "哈", "哎", "呀", "哇",
    "吗", "嘛", "啦", "咯", "呵", "嘿",
    # 中文标点(单字)
    "、", "。", "？", "！", "，", "；", "：", "（", "）", "【", "】", "《", "》",
    # 英文虚词
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "i", "you", "he", "she", "it", "we", "they", "them", "their",
    "and", "or", "but", "so", "if", "then",
    "to", "of", "in", "on", "at", "for", "with", "by", "from",
    "this", "that", "these", "those",
    "do", "does", "did", "doing",
    "have", "has", "had",
    "as", "about", "into", "than", "until", "while",
    "up", "down", "out", "off", "over", "under", "again", "further",
    "very", "just", "only", "also", "now", "here", "there",
    "when", "where", "why", "how", "all", "any", "both", "each",
    "few", "more", "most", "other", "some", "such", "no", "nor",
    "not", "own", "same", "too", "can", "will", "would", "should",
    # 通用高频动词(不构成主题)
    "used", "use", "using", "make", "made", "make", "doing", "done",
    "work", "working", "works", "worked", "go", "going", "went", "gone",
    "get", "got", "getting", "take", "took", "taking", "give", "gave",
    "know", "knew", "known", "think", "thought", "see", "saw", "seen",
    "want", "wanted", "need", "needed", "try", "tried", "trying",
    "问", "答", "说", "讲", "聊", "想", "看", "找", "给", "帮", "让",
    "使用", "用过", "做过", "了解", "熟悉", "知道", "觉得", "认为",
    "比较", "非常", "特别", "真的", "其实", "可能", "应该", "需要",
})


# PII 后缀 regex:匹配 公司/集团/LLC/Inc 等组织后缀及其前面的实体名
# 设计:不预设具体公司名,通过后缀模式识别;entity 与 suffix 之间允许空格。
_PII_PATTERNS: tuple[re.Pattern[str], ...] = (
    # 中文组织后缀:XXX公司 / XXX 集团 / XXX有限(可选空格)
    re.compile(r"[一-鿿A-Za-z0-9]+\s*(?:有限公司|有限责任公司|股份有限公司|集团|公司|工作室|部门)"),
    # 英文公司后缀:XXX LLC/Inc/Corp/Co./Ltd.(IGNORECASE:覆盖 foo inc / Acme LLC)
    re.compile(r"\b[A-Z][A-Za-z0-9&\.\-]*\s+(?:LLC|L\.L\.C\.|Inc\.?|Incorporated|Corp\.?|Corporation|Co\.?|Ltd\.?|Limited|LP|LLP|PLC|GmbH|S\.A\.)\b", re.IGNORECASE),
    re.compile(r"\b(?:LLC|L\.L\.C\.|Inc\.?|Incorporated|Corp\.?|Corporation|Co\.?|Ltd\.?|Limited|LP|LLP|PLC|GmbH|S\.A\.)\b"),
    # 项目代号常见格式 + 代号值
    # "项目代号 Phoenix" / "代号 PRJ-001" / "代号名 Phoenix-X" / "Project Phoenix" / "代号_Phoenix"
    re.compile(r"(?:项目代号|代号名)\s+[A-Za-z][A-Za-z0-9_\-]*"),
    re.compile(r"Project\s+[A-Z][A-Za-z0-9_\-]*", re.IGNORECASE),
    re.compile(r"PRJ[\-_][A-Z0-9]+", re.IGNORECASE),
    re.compile(r"代号[\-_][A-Za-z0-9]+"),
)


# 同义词聚类:多源术语 fold 到 canonical key
# 设计:canonical 一律小写英文短语,中文 / 缩写 / 全拼都 fold 到同一 key
_SYNONYM_MAP: dict[str, str] = {
    # 性能 / 吞吐
    "性能": "performance",
    "perf": "performance",
    "performance": "performance",
    "throughput": "throughput",
    "qps": "throughput",
    "tps": "throughput",
    "rps": "throughput",
    "吞吐": "throughput",
    "吞吐量": "throughput",
    # 高可用
    "高可用": "high_availability",
    "ha": "high_availability",
    "high availability": "high_availability",
    "high-availability": "high_availability",
    # 分布式
    "分布式": "distributed",
    "distribution": "distributed",
    "distributed": "distributed",
    # 一致性
    "一致性": "consistency",
    "consistency": "consistency",
    # 事务 / 锁
    "事务": "transaction",
    "transaction": "transaction",
    "tx": "transaction",
    "分布式锁": "distributed_lock",
    "分布式事务": "distributed_transaction",
    # 缓存
    "缓存": "cache",
    "cache": "cache",
    "caching": "cache",
    # 数据库
    "数据库": "database",
    "db": "database",
    "database": "database",
    "sql": "sql",
    "mysql": "mysql",
    "postgres": "postgres",
    "postgresql": "postgres",
    # 微服务
    "微服务": "microservice",
    "microservice": "microservice",
    "microservices": "microservice",
    "服务化": "microservice",
    # 消息队列
    "消息队列": "message_queue",
    "mq": "message_queue",
    "message queue": "message_queue",
    "kafka": "kafka",
    "rabbitmq": "rabbitmq",
    "rocketmq": "rocketmq",
    # 容器 / 编排
    "docker": "docker",
    "容器": "docker",
    "kubernetes": "kubernetes",
    "k8s": "kubernetes",
    "k8": "kubernetes",
    # 监控 / 可观测
    "监控": "monitoring",
    "monitoring": "monitoring",
    "可观测": "observability",
    "observability": "observability",
    "链路追踪": "tracing",
    "tracing": "tracing",
    # CI/CD
    "ci": "ci_cd",
    "cd": "ci_cd",
    "ci/cd": "ci_cd",
    "cicd": "ci_cd",
    # 系统设计
    "系统设计": "system_design",
    "system design": "system_design",
    "system_design": "system_design",
    # 算法
    "算法": "algorithm",
    "algorithm": "algorithm",
    "algorithms": "algorithm",
    # 数据结构
    "数据结构": "data_structure",
    "data structure": "data_structure",
    "data_structure": "data_structure",
    # 网络
    "网络": "network",
    "network": "network",
    "networking": "network",
    "tcp": "network",
    "http": "network",
    # 安全
    "安全": "security",
    "security": "security",
    "鉴权": "auth",
    "认证": "auth",
    "authorization": "auth",
    "authentication": "auth",
    "auth": "auth",
}


# 阈值常量(可在 extract_topics 参数覆盖)
DEFAULT_MIN_TF = 3
DEFAULT_MIN_RATIO = 0.05


# ============================================================================
# 文本处理 helpers
# ============================================================================


_TOKEN_RE = re.compile(r"[一-鿿]+|[A-Za-z][A-Za-z0-9]*|[0-9]+")


def _is_cjk(ch: str) -> bool:
    return "一" <= ch <= "鿿"


def _mask_pii(text: str) -> str:
    """用空格替换 PII 实体(公司名 / 项目代号 / 后缀)。"""
    out = text
    for pat in _PII_PATTERNS:
        out = pat.sub(" ", out)
    return out


def _tokenize_cjk_2gram(text: str) -> list[str]:
    """CJK 2-gram sliding window + 英文/数字整词。

    与 authenticity.py:_content_tokens 一致算法,但**返回 list**而非 set,
    因为我们要算 tf(词频)而不是 unique 集合。
    """
    out: list[str] = []
    for m in _TOKEN_RE.finditer(text):
        tok = m.group().lower()
        if not tok:
            continue
        if all(_is_cjk(c) for c in tok):
            # CJK run 内 sliding window size 2,过滤含停用字的 bigram
            for i in range(len(tok) - 1):
                bg = tok[i:i + 2]
                if bg[0] in _STOPWORDS or bg[1] in _STOPWORDS:
                    continue
                out.append(bg)
        elif len(tok) >= 2:
            if tok not in _STOPWORDS:
                out.append(tok)
    return out


def _apply_synonyms(tokens: list[str]) -> list[str]:
    """同义词聚类:每 token 查 SYNONYM_MAP,命中替换 canonical。

    lookup 是 lowercase:canonical key 已全小写,token 任意大小写都 fold 到同一 key。
    """
    return [_SYNONYM_MAP.get(t.lower(), t) for t in tokens]


def _compute_tf(tokens: list[str]) -> dict[str, int]:
    """词频计数。Counter 包装,显式返回 dict 方便测试。"""
    return dict(Counter(tokens))


def _filter_by_thresholds(
    tf: dict[str, int],
    total: int,
    min_tf: int = DEFAULT_MIN_TF,
    min_ratio: float = DEFAULT_MIN_RATIO,
) -> list[tuple[str, int]]:
    """双阈值过滤:min_tf AND min_ratio。返回 [(topic, tf), ...] 排序后。"""
    if total <= 0:
        return []
    out: list[tuple[str, int]] = []
    for topic, count in tf.items():
        if count < min_tf:
            continue
        if count / total < min_ratio:
            continue
        out.append((topic, count))
    out.sort(key=lambda kv: (-kv[1], kv[0]))
    return out


# ============================================================================
# 公共 API
# ============================================================================


def extract_topics(
    turns: list[dict],
    *,
    min_tf: int = DEFAULT_MIN_TF,
    min_ratio: float = DEFAULT_MIN_RATIO,
) -> list[TopicFact]:
    """从 interview turns 提取 topic 列表。

    Pipeline:
        1. 过滤 user-role 的 turns(保留原 idx)
        2. Per-turn: PII mask → tokenize → synonym fold
        3. 汇总 tf + 记录每个 topic 首次出现的 user turn idx
        4. Filter by min_tf AND min_ratio
        5. 转为 TopicFact, score = tf / total_tokens

    Args:
        turns: turn dict 列表,每条含 {"role", "content"}
        min_tf: 最小词频,默认 3
        min_ratio: 最小词频 / 总词数,默认 0.05

    Returns:
        TopicFact 列表,按 score DESC, topic ASC 排序。
        空 turns / 全空 content / 不达阈值 → 返回 []。
    """
    user_turns = [(i, t) for i, t in enumerate(turns) if t.get("role") == "user"]
    if not user_turns:
        return []

    # per-turn token list + first-occurrence index
    per_turn_tokens: list[list[str]] = []
    for _idx, t in user_turns:
        content = str(t.get("content", "")).strip()
        if not content:
            per_turn_tokens.append([])
            continue
        masked = _mask_pii(content)
        per_turn_tokens.append(_apply_synonyms(_tokenize_cjk_2gram(masked)))

    total = sum(len(toks) for toks in per_turn_tokens)
    if total <= 0:
        return []

    tf: dict[str, int] = {}
    first_seen: dict[str, int] = {}
    for ut_idx, toks in enumerate(per_turn_tokens):
        for tok in toks:
            tf[tok] = tf.get(tok, 0) + 1
            if tok not in first_seen:
                first_seen[tok] = user_turns[ut_idx][0]

    filtered = _filter_by_thresholds(tf, total, min_tf=min_tf, min_ratio=min_ratio)
    if not filtered:
        return []

    return [
        TopicFact(
            topic=topic,
            score=round(count / total, 6),
            source_turn=first_seen[topic],
        )
        for topic, count in filtered
    ]