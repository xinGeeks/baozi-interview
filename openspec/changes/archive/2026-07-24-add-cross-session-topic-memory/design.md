## Context

BaoZi-Interview v0.3 Streamlit MVP 已稳定 242 测试全绿,包含 5 项 feature(A 即时反馈、B 历史持久化、C 流式输出、D 打分校准、E 真实性检测)+ alpha-kickoff(ToS / 成本 / 删除 / 韧性)+ UX 收口(折叠 / 单用户 / popover)。

`storage.py` 当前 4 表:`interview_sessions` / `interview_turns` / `turn_feedback` / `consent_log`。单用户模式 `candidate_id="default"`,所有 session 共享一个 candidate。

每次 `save_session` 后,turns 写入 `interview_turns` 但没有任何 topic 抽取 / 聚合层。`authenticity.py` 已用 CJK 2-gram sliding window 做实体识别(<1ms,零依赖),可复用 tokenize 算法。

**Stakeholders**:求职者(看 topic cloud / trend)、开发者(在 `app.py` sidebar 加折叠区)、单用户工具的所有者(隐私:本地 SQLite,不上云)。

## Goals / Non-Goals

**Goals:**
- 在 `interview_turns` 之上叠加 topic 抽取 + 跨 session 聚合,落地 `topic_facts` 事实表 + `candidate_topic_cache` 聚合 cache 表
- 复用 `authenticity.py` 的 CJK 2-gram 算法,保持零新依赖
- sidebar 新增折叠 expander(沿用 v0.3 UX 收口的「默认折叠」模式),内含 topic cloud(HTML chip + 字号映射 score)+ trend chart(`st.bar_chart` 每 topic 跨 session 平均得分)
- save_session 落盘后 inline 触发抽取,失败 best-effort
- PII 边界:topic 抽取前置过滤公司名 / 项目代号 / 通用敏感词

**Non-Goals:**
- LLM 抽取(MVP 阶段零 LLM 成本优先)
- 实时聚合(只有 session 结束后才抽取)
- 多用户隔离(单用户工具,`candidate_id="default"` 已硬编码)
- 后台 worker / 队列 / 异步任务
- Topic drill-down / per-session topic 详情(本期只到聚合级)

## Decisions

### 1. Tokenize 用 CJK 2-gram sliding window(零依赖)
**Why**:authenticity.py 已落地该算法,<1ms,无 jieba 启动开销。jieba 是可选增强但本期不加(避免 `requirements.txt` 新增一行)。
**Alternative 考虑**:jieba 词更准但启动 ~500ms + 增加 15MB 依赖;MVP 启发式精度够用,2-gram 已在生产验证(真实性检测)。

### 2. 双表存储(topic_facts 事实 + candidate_topic_cache 聚合)
**Why**:topic_facts 保留 per-session provenance(后续 drill-down 用),candidate_topic_cache 是 O(1) 读 cache(topic cloud 直接读 cache)。`extract_and_store_for_session` 写两张表,事务。
**Alternative 考虑**:只用一张 `candidate_topic_cache` 会丢失 per-session 关联,未来 drill-down 必须回退加表;现在双表代价是 ~30 行,值。

### 3. Inline 抽取在 save_session 后
**Why**:单用户工具,单 session turns 通常 <30 条,tokenize + 同义词 fold + score 归一预计 <500ms。inline 简单可靠,不引后台进程。
**Alternative 考虑**:后台线程 / 队列会增加复杂度和测试面(alpha-kickoff 韧性原则:能 inline 就别异步)。

### 4. UI 折叠 expander + HTML chip + st.bar_chart
**Why**:
- v0.3 UX 收口统一默认折叠,sidebar expander 不占主区空间
- topic cloud 用 `st.markdown(unsafe_allow_html=True)` 渲染不同字号的 `<span>`,轻量无新依赖
- trend chart 用 `st.bar_chart`(Streamlit 内置,无新依赖)展示 top-10 topic 跨 session 平均得分

**Alternative 考虑**:`streamlit-elements` / `streamlit-echarts` 加新依赖;`wordcloud` 库装 matplotlib/fonttools(~10MB)。

### 5. PII 过滤:STOPWORDS + 实体 mask
**Why**:`authenticity.py:detect_signals` 已用 ~20 条实体 stopword + substring matching。同思路扩到 ~50 条中文 PII + 英文公司后缀(LLC / Inc / Corp / 公司 / 集团)+ ~80 条通用 stopword。mask 后再走 tokenize。
**Alternative 考虑**:LLM 抽取可识别 PII 但本期不上;正则匹配覆盖 80% 常见 PII。

### 6. 阈值 min_tf=3 AND min_ratio=0.05
**Why**:沿用 evals/phase_e/topic_extraction 同阈值(业界常见 spam filter),短会话被高频词覆盖 false positive fold 比 false negative 好(同 topic 不重复列)。
**Alternative 考虑**:min_tf=2 太松(单 session 1 个常用词就上榜),min_tf=5 太严(短会话全军覆没)。

### 7. 不引入 SCHEMA_VERSION bump
**Why**:仅 ADD 新表(`CREATE IF NOT EXISTS`),现有 4 表数据 100% 保留。新表独立 topic_facts / candidate_topic_cache 互不影响。
**Alternative 考虑**:加 SCHEMA_VERSION=2 是为后续跨版本迁移铺路,但目前迁移函数 `_migrate_v1_to_v2` 还没必要写;留到下一次破坏性 schema 改动时再统一 bump。

## Risks / Trade-offs

- **[Risk] Topic 噪声(common word 当 topic)** → Mitigation:`min_tf=3 AND min_ratio=0.05` 双门槛 + 同义词 fold + ~80 条 stopword + ~20 PII mask。
- **[Risk] PII 泄漏(公司名 / 项目代号成 topic)** → Mitigation:mask 在 tokenize 之前;topic_facts 仅存 topic 字符串,不存原 turn 文本。
- **[Risk] Inline 抽取阻塞 UI** → Mitigation:`extract_and_store_for_session` 包 `try/except Exception`,失败 `st.session_state.error_msg` 不弹窗(静默);UI 永远可交互。
- **[Risk] 冷启动(首场无聚合)** → Mitigation:sidebar expander 空态显示「暂无跨 session 数据,完成第 2 场后会自动出现」;首次完成 session 后聚合 cache 是空 list。
- **[Risk] 单用户硬编码导致 candidate_id 写死** → Mitigation:沿用 `storage.get_candidate_id()`,未来多用户只改一个函数。
- **[Trade-off] 2-gram 词边界不精准** → 接受。MVP 阶段精度足够启发式,LLM 增强是 v0.4 路线。
- **[Trade-off] 无 per-session topic drill-down** → 接受。本期只到聚合 UI,drill-down 留给后续变更。
- **[Trade-off] topic_facts 表随 session 线性增长** → 接受。SQLite 单表 <1M 行无忧;真到瓶颈再分表。

## Migration Plan

无破坏性数据迁移。两张新表都 `CREATE IF NOT EXISTS`,旧库自动获得新表。

**Rollback**:`DROP TABLE topic_facts; DROP TABLE candidate_topic_cache;`(两行 SQL,无外部依赖)。`save_session` 触发点是 try/except 包裹,删表后 inline 调用直接空跑,UI 仍正常。

## Open Questions

- Q1:topic cloud 字号映射函数是线性 `font_size = 12 + score * 24`(score 0..1 → 12..36px),还是开根号缓变?倾向线性(简单,score 已归一化)。**已默认线性,实施时可调。**
- Q2:`get_topic_trend` 返回多少个 session 的窗口(默认全量 vs 最近 N)?倾向全量(单用户数据量小)。**已默认全量。**
- Q3:sidebar expander 内是否加「查看更多 → 历史 session 详情」链接?本期不做,留 v0.4。