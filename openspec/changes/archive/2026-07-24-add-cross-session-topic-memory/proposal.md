## Why

求职者在 v0.3 MVP 上做多场模拟面试,但每场都是孤立快照 —— 没有跨 session 的"练了什么 / 什么反复弱"的反馈,陷入无方向循环练习。把单次教练升级为长期教练,需要在单用户 SQLite 上落地跨 session topic 聚合与可视化。

## What Changes

- 新增 `topic_extraction.py` 纯函数模块:CJK 2-gram sliding window + 同义词聚类 + PII 过滤,零 LLM 成本。
- 扩展 `storage.py`:新增 `topic_facts(sid, topic, score, source_turn)` 表(幂等 `CREATE IF NOT EXISTS`)与 `candidate_topic_cache(candidate_id, topic, score)` 聚合 cache 表;新增 `write_topic_facts` / `get_topics_for_candidate` / `get_topic_trend` / `extract_and_store_for_session`。
- 修改 `save_session` 调用点(app.py `_generate_report`):落盘后 inline 调用 `extract_and_store_for_session`,失败 best-effort,不阻断 UI 与持久化。
- 修改 `app.py` sidebar:新增折叠 expander「🎯 跨会话训练图谱」(默认折叠,与 v0.3 UX 收口一致),内含 topic cloud(HTML chip + 字号 = 频率)和 trend chart(`st.bar_chart` 每 topic 跨 session 平均得分)。
- 新增 `tests/test_topic_extraction.py` 与 `tests/test_storage_topics.py`,覆盖 tokenize / 同义词 fold / PII mask / 存储 / 聚合。
- 新增 `openspec/specs/cross-session-topic-memory/spec.md`。

## Capabilities

### New Capabilities

- `cross-session-topic-memory`:跨 session topic 抽取、聚合、缓存、可视化;覆盖提取算法契约、存储表 schema、UI 触发点、空态与 PII 边界。

### Modified Capabilities

(无。当前是新增能力,既有 spec 不需要 REQUIREMENTS 级改动。)

## Impact

- **代码**:新增 `topic_extraction.py`;`storage.py` +~120 行(表 + 函数,保持幂等迁移);`app.py` +~40 行(sidebar expander + 触发点);`tests/` +2 文件。
- **依赖**:零新增。`sqlite3` / `re` / `html.escape` 均为 stdlib;`st.bar_chart` 已随 Streamlit 可用。
- **数据**:旧库 4 表数据 100% 保留(topic_facts / candidate_topic_cache 是新表,`CREATE IF NOT EXISTS`)。
- **测试**:目标 +35~45 测试(`test_topic_extraction` ~25 单元、`test_storage_topics` ~10 集成),期望总数 242 → ~285 全绿。
- **UI**:仅 sidebar 新增折叠区,主对话流 / 报告区 / 历史区一字不动。