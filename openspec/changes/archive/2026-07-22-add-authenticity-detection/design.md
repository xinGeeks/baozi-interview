## Context

v0.3 已有:
- `feedback.py` per-turn 即时评分(单维度 0-10,启发式锚定)
- `prompts.py` 报告生成(六维度 + 反虚高天花板)
- `app.py` 主对话循环 + 报告渲染

痛点:**反馈系统对"看起来好"vs"真的好"无感**。两类典型欺骗模式:
1. 简历夸大(简历写"参与",回答描述成"主导")
2. 模板化/泛泛而谈(无具体细节但也未直接跑题)

需要新模块在保持现有性能预算(<2s/turn)的前提下,补"真实性"这一维度。

## Goals / Non-Goals

**Goals:**
- 启发式 per-turn 检测:零 LLM 成本,<1ms/turn
- 报告时单次 LLM 聚合:沿用现有报告 prompt 时序,串行 ~2s
- UI 透出:逐轮反馈卡显示 ⚠️,报告新增「第 7 段 · 真实性维度」
- 完全向后兼容:所有新字段可选,旧调用点零改动

**Non-Goals:**
- 训练自定义分类器(用启发式 + LLM-as-judge 够用)
- 跨 session 跨 candidate 比对(单场即可)
- LLM token 级流式输出(本变更不碰 streaming)
- HR 侧报告 / 录用决策(本服务是求职者练习)

## Decisions

### Decision 1: Heuristic-only per-turn, LLM-only at report end

**选择**:per-turn 不调 LLM,只跑启发式(<1ms);LLM 聚合只在 `_end_interview` 报告生成末尾走 1 次。

**Why**:per-turn 已有一个 `chat()`(~2-3s)+ 一个 `feedback()`(~1-2s),再加 LLM 检测会拖到 ~6-8s/turn,UX 不可接受。报告生成时一次性聚合,只多 1 次 LLM 调用,与报告本身 ~10s 串行,边际成本低。

**Alternatives considered**:
- A. 每 turn 跑 LLM 检测 → 成本 50-100% 提升,否决
- B. 只在 report 时跑(放弃 per-turn UI)→ 用户练不到当下,体验打折
- C. 选中:启发式 + report-time 聚合 — 启发式覆盖高频信号,LLM 兜底做简历对齐

### Decision 2: Heuristic signals (4 条)

```python
def detect_signals(question: str, answer: str, resume_text: str) -> list[str]:
    flags = []
    if len(answer.split()) < 8 and "?" not in answer:
        flags.append("过于简短")  # <8 词且非反问
    generic = ["很多东西", "很多项目", "比较熟悉", "有所了解", "负责过"]
    if any(g in answer for g in generic) and not any(c.isdigit() for c in answer):
        flags.append("模板化")  # 含泛词但无任何数字
    q_words = set(jieba.cut(question)) - STOPWORDS
    a_words = set(jieba.cut(answer)) - STOPWORDS
    if q_words and len(q_words & a_words) / len(q_words) < 0.15:
        flags.append("答非所问")  # 关键词重叠 < 15%
    if resume_text and not _mentions_any_entity(answer, resume_text):
        flags.append("未引用简历")  # 答案没提任何简历里出现过的实体(项目名/技术栈)
    return flags
```

**Why 这 4 条**:经验覆盖最常见的 4 类信号(短答 / 套话 / 跑题 / 简历游离);每条都可独立测试;总成本 <1ms。jieba 已是依赖(memory)。

### Decision 3: LLM 聚合 prompt 强约束

**选择**:prompt 末尾加「只基于 given signals 推断,不得编造 finding;若 signals 为空,score=1.0 + findings=[]」。

**Why**:LLM 幻觉是最大风险点。强制 ground 到 signals 是已知反幻觉技巧(Mitigating LLM Judge Bias,Zheng et al. 2023)。

### Decision 4: 输出格式 — flag-only,不阻断

**选择**:UI 显示 ⚠️ + 一句话,**不修改分数**。即 "答非所问" 的 turn 仍可拿 6 分(因为可能"礼貌地不答"),但用户能看到 ⚠️ 自查。

**Why**:MVP 不应该让算法决定"挂科"。给信号让人判断,符合"教练,不是雇主"的 v0.3 设计基调。

### Decision 5: Backward compat via Optional fields

**选择**:所有新 dataclass 字段默认 `None` 或 `[]`,`build_report_prompt` / `build_feedback_prompt` 不传时输出不变。

**Why**:不破坏 v0.3 既有 134 测试;旧调用点零改动。

## Risks / Trade-offs

- **R1: 启发式误判** (校招 Q&A 短答可能合理) → 只标"过于简短"时显示 warning 而非红色;UI 不强制弹窗
- **R2: LLM 聚合幻觉** → prompt 强约束"基于 signals",并在 parse 容错:findings > 3 条时截断,score 越界截到 [0,1]
- **R3: 报告长度膨胀** → 第 7 段 ≤ 200 字硬约束,parse 时 enforce
- **R4: jieba 切词质量影响关键词重叠** → 设 STOPWORDS 白名单(常见虚词/中文标点),test fixture 验证中文短答不被误标
- **R5: per-turn UI 加图标可能影响 mock 测试** → `at.session_state["turn_authenticity_flags"]` 注入,AppTest 验证有/无 flag 两种渲染