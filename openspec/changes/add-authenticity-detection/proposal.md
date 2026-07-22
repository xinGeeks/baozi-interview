## Why

当前 v0.3 反馈系统能给候选人"答得怎么样"的评分,但**没法区分"答得好"和"答得看似好"**。两类欺骗模式会污染报告:

1. **简历 vs 回答不一致**:简历写"参与订单系统重构",回答里却描述成"主导"+"从 0 到 1"
2. **编造 / 模板化**:"我做过很多项目,涉及高并发、分布式,具体细节..."这类泛泛而谈,既不犯大错也提供不了证据

求职者实战模拟的价值在于"暴露弱点",如果报告对这两类信号无感,候选人练完提升有限。

## What Changes

新增 **真实性检测 (authenticity detection)** 模块,双轨设计:

1. **Per-turn 启发式标记**(零 LLM 成本):4 条轻量规则检测可疑信号 → 给每轮打 `authenticity_flags: list[str]`(空 = 无问题)
2. **报告时 LLM 聚合**(单次 ~2s 调用):把全部 turns + 简历 + JD + 启发式 flagged turns 一起喂给 LLM,生成 `authenticity_report: {score: 0-1, findings: list[Finding], summary: str}`

UI 改动:
- 逐轮反馈卡:有 flag 时显示 ⚠️ + 一句话原因(无 flag 不显示)
- 复盘报告:新增「第 7 段 · 真实性维度」段,展示均分 + 关键发现 + 摘要

不破坏现有接口:`build_feedback_prompt` / `parse_feedback_response` / `build_report_prompt` 输出**向后兼容**(新字段可选,旧调用点忽略)。

## Capabilities

### New Capabilities

- `authenticity-detection`: 启发式 per-turn 标记 + 报告时 LLM 聚合,产出 `authenticity_flags`(per turn)和 `authenticity_report`(整场面试),UI 在逐轮卡和报告页透出

### Modified Capabilities

<!-- v0.3 之前无 spec 目录,无现有 capability 可改 -->

## Impact

- **新文件**:
  - `authenticity.py` — `detect_signals(question, answer, resume_text) -> list[str]`(启发式)+ `build_authenticity_judgment_prompt(...)` + `parse_authenticity_response(text) -> AuthenticityReport`
  - `tests/test_authenticity.py` — 启发式纯函数测试 + parse 容错测试 + snapshot 测试 prompt
- **修改文件**:
  - `feedback.py` — `build_feedback_prompt` 末尾追加「真实性提示」段(轻微,不动 parse)
  - `prompts.py` — `build_report_prompt` 末尾追加「第 7 段 · 真实性维度」结构
  - `app.py` — `_handle_user_answer` 在 feedback 后调 `detect_signals` 标 flag;`_end_interview` 报告生成后调一次 LLM 聚合,结果存 `session_state["authenticity_report"]`
  - `tests/test_app.py` — 加 2-3 个 AppTest 验证 UI 显示
- **新增依赖**:无(jieba/Pydantic 已有,LLM 走现有 `chat()`)
- **性能影响**:per-turn 启发式 < 1ms;报告时 +1 次 LLM 调用(~2s,与现有报告生成串行)
- **风险点**:
  - LLM 聚合可能产生幻觉(报告里"发现"了实际不存在的问题)→ 通过启发式先验 + prompt 强约束「只基于 given signals 推断」
  - 启发式规则可能误判短回答(校招 Q&A 可能就是简短)→ 给每条规则加 confidence / 权重,UI 显示时只露 ≥2 条 flag 才标红