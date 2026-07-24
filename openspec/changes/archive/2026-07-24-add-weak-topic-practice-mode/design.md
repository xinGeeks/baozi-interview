## Context

现状:Feature F(commit `a87b3a2`)让 sidebar `🎯 跨会话训练图谱` 显示高频 topic 词云 + Top-10 趋势柱 + per-topic 折线。但用户看到"反复提到 kafka"后没有行动路径 — 必须手动开新面试、自己写 JD、自己开题。

本 change 加一个"专项训练"模式:点 cache 候选 → 进焦点面试 → 围绕该 topic 深挖 → 退出后落盘为 practice session,**不污染**训练图谱(避免"练越多、图谱越偏"的反馈循环)。

约束:
- 复用现有 `_start_interview` / `_handle_user_answer` / `_generate_report` 流程,不改主对话循环
- 复用 `extract_and_store_for_session`,只加 mode gate,不引入新 storage helper
- 零新依赖
- 单用户模式(candidate_id="default")不变

## Goals / Non-Goals

**Goals:**
- 让用户从 cache 高频 topic 一键进入专项训练
- LLM 围绕焦点主题深挖(基础 → 场景 → 坑 → 简历交叉)
- practice session 落盘后**不**进入 candidate_topic_cache
- history 区有独立的"练习记录"子区,方便用户回看

**Non-Goals:**
- 不做"按质量选 topic"(需要 topic↔turn 评分映射,留 Phase 2)
- 不做"多 topic 同时练习"或"中途切换焦点"
- 不做 practice 报告 vs interview 报告的对比
- 不做 spaced-repetition / 间隔重复调度
- 不做 practice transcript 二次抽取回写 cache(刻意 gate,防污染)

## Decisions

### Decision 1: storage mode 列(非新表)

**选**:在 `interview_sessions` 加 `mode TEXT NOT NULL DEFAULT 'interview'`,老行 backfill。

**理由**:
- 复用现有 ON DELETE CASCADE 行为(`delete_session` 已 cascade 到 turns/feedback)
- 一个 session 表,UI 渲染逻辑统一(history view 已能读)
- 幂等迁移(PRAGMA table_info + ALTER TABLE),老 DB 兼容

**备选**:
- 新表 `practice_sessions`:多一层 JOIN,UI 渲染要分支;增加 schema 复杂度
- 用 jd_summary 前缀(例如 `[PRACTICE] kafka...`):grep 友好但难做 strict filter
- ✅ mode 列:简单 + 可索引 + 不破坏现有

### Decision 2: extract_and_store_for_session 内部 gate(非 app.py 端 gate)

**选**:在 `extract_and_store_for_session` 入口查 `SELECT mode`,mode='practice' → return 0(不写 cache)。

**理由**:
- 防"app.py 忘调 gate"的回归:任何调用路径(storage CLI、test、app)都受保护
- 与现有"失败返回 0 不抛"的语义一致,主流程无感

**备选**:
- app.py 端 gate:依赖调用方自觉,易漏
- ✅ storage 端 gate:契约式,API 语义清晰

### Decision 3: prompts 扩展 focus_context(非新 prompt 函数)

**选**:`build_interviewer_system_prompt(..., *, focus_context=None)`,非 None 时在 prompt 末尾(开场白前)注入 `[专项训练模式]` 块。

**理由**:
- 单一 surface,只 focus block 变化,prompt drift 最小
- 现有 6 档 × 2 风格的 base prompt 不变,snapshot 测试零破坏

**备选**:
- 新 `build_practice_interviewer_system_prompt` 函数:DRY 失守,base 改 1 处要改 2 处
- ✅ 扩展模式:在 base 末尾追加 block,base 单源

### Decision 4: practice 模式不写 JD(skill 跳过 JD 校验)

**选**:`_start_interview` 在 `practice_mode=True` 时跳过 `jd_content.strip()` 非空校验。JD 字段在 save 时填空串。

**理由**:
- focus_context 已替代 JD 的"训练方向"角色,JD 重复无意义
- 避免用户在 practice 入口被"请先填 JD"卡住(认知负担)
- save_session 的 jd 仍存(空串,backward-compat)

**备选**:
- 要求 practice 也填 JD(类似"焦点是 JD 的子集"):增加 UX 摩擦,无收益
- ✅ 跳过:practice 是"无需准备"的快捷入口

### Decision 5: chat_input 退出信号("退出专项训练")

**选**:用户输入"退出专项训练"等同 END_SIGNAL(结束 + 出报告),并清 practice_mode。

**理由**:
- 与现有 END_SIGNAL 路径统一,无需新流程
- 显式关键词(不是隐式规则)更清晰

## Risks / Trade-offs

- **Risk**:practice 模式 cache 隔离通过 mode gate 强制,但 cache.score 是该 topic 的最大提及占比,不会被 practice 抬高。**这正是预期行为** — practice 是"看 + 练"的 drill-down,不增加"反复提到"信号(否则训练图谱会无限滚动 kafka 等等)。
- **Risk**:AppTest 5+ at.run() 在 4-轮 interview 路径上偶发超时(60s 不够,需 120s)。**Mitigation**:已为 `test_interview_mode_not_affected_by_practice_changes` 单独 default_timeout=120;其他 practice 测试 60s 稳。
- **Risk**:practice 退出后,`practice_mode` session_state 残留可能导致下次正常 start 自动进入 practice 模式。**Mitigation**:`_start_interview` 内不主动清 practice_mode,但每次"开始面试"按钮在 `interview_started=True` 时 disabled;exit button / text signal / "🛑 结束面试并出报告" 三条路径都显式 reset(`st.session_state.practice_mode = False`)。
- **Trade-off**:practice 模式不做 turn limit,用户可能一直聊到 token 预算爆。**接受**:与现有 normal interview 行为一致(token 预算条 + budget block 已防护)。

## Migration Plan

1. **代码**:storage.py 加 mode 列 + 幂等迁移(python 启动时 init_db 自动跑)
2. **数据**:老 DB 第一次 init_db → `ALTER TABLE ... ADD COLUMN mode TEXT NOT NULL DEFAULT 'interview'`,老行自动 backfill
3. **回滚**:如需回滚,删除新代码即可,mode 列在 SQLite 保留也无害(save_session 默认 'interview')
4. **UI**:无 breaking change — 老用户的 history 显示不变(都是 interview 模式)

## Open Questions

- 暂无
