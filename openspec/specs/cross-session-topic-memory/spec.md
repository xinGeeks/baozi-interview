# cross-session-topic-memory Specification

## Purpose
TBD - created by archiving change add-cross-session-topic-memory. Update Purpose after archive.
## Requirements
### Requirement: Rule-based topic extraction with zero LLM cost

The system SHALL extract topics from interview turns using a rule-based algorithm (CJK 2-gram sliding window + synonym clustering) without invoking any LLM, returning `list[TopicFact(topic: str, score: float 0..1, source_turn: int)]`.

#### Scenario: Single turn produces topic list
- **WHEN** `extract_topics(turns=[{"role":"user","content":"我设计了一个分布式锁"}])` is called
- **THEN** returned list contains at least one topic whose string is a 2-gram of the input (e.g. `"分布式锁"`) with score in `[0, 1]`

#### Scenario: Mixed CJK + English tokenized
- **WHEN** input contains both Chinese (e.g. `"高并发"`) and English (e.g. `"Redis"`) substrings
- **THEN** both surface as topics (Chinese via 2-gram, English via whitespace split + length filter)

#### Scenario: Empty input returns empty list
- **WHEN** `extract_topics(turns=[])` or all turns have empty `content`
- **THEN** returned list is `[]`

### Requirement: Topic aggregation filters noise via dual thresholds

The system SHALL apply `min_tf=3` AND `min_ratio=0.05` (term-frequency threshold AND ratio of total tokens) before exposing a topic to the UI cache, so common words and short-session outliers do not surface.

#### Scenario: High-frequency topic passes both thresholds
- **WHEN** topic `"分布式"` appears ≥ 3 times AND its ratio of total tokens ≥ 0.05 across the candidate's turns
- **THEN** the topic is written to `candidate_topic_cache`

#### Scenario: Common word fails min_tf
- **WHEN** topic `"系统"` appears only once across all turns
- **THEN** the topic is filtered out before cache write

#### Scenario: Short-session outlier fails min_ratio
- **WHEN** a single-session candidate with 5 turns has a topic covering 30% of tokens but appears only once (ratio passes but tf fails)
- **THEN** the topic is filtered out by min_tf=3

### Requirement: PII masking before tokenization

The system SHALL strip PII entities (company names, project codenames, generic suffix words like `公司`/`集团`/`LLC`/`Inc`/`Corp`) and ~80 stopwords from turn text BEFORE running tokenization, so topics surfaced to the UI never contain identifying information.

#### Scenario: Company name stripped from turn text
- **WHEN** turn contains `"我在 Acme 公司做了订单系统"`
- **THEN** tokenized topics do NOT include `"Acme"`, `"公司"`, or `"Acme公司"` as standalone topics

#### Scenario: Stopwords removed
- **WHEN** turn contains common words like `"的"`/`"`是`"`/`"了"`/`"和"`
- **THEN** none of these single-character stopwords surface as topics

#### Scenario: PII masking is case-insensitive for English suffixes
- **WHEN** turn contains `"FooCorp"` and `"Foo Inc"` and `"BAR LLC"`
- **THEN** all three names are stripped before tokenization

### Requirement: Dual-table storage schema for provenance and O(1) aggregate read

The system SHALL create two new SQLite tables via `CREATE TABLE IF NOT EXISTS`: `topic_facts(sid TEXT, topic TEXT, score REAL, source_turn INTEGER, PRIMARY KEY(sid, topic, source_turn))` and `candidate_topic_cache(candidate_id TEXT, topic TEXT, score REAL, last_seen_at TEXT, PRIMARY KEY(candidate_id, topic))`, so per-session drill-down and per-candidate UI read both work without full-table scans.

#### Scenario: New tables created on first init_db
- **WHEN** `init_db()` is called on a fresh database
- **THEN** `sqlite_master` contains `topic_facts` and `candidate_topic_cache`

#### Scenario: Existing 4 tables untouched
- **WHEN** `init_db()` is called on a database created by v0.3
- **THEN** `interview_sessions`, `interview_turns`, `turn_feedback`, `consent_log` retain all existing rows

#### Scenario: INSERT OR IGNORE makes repeat extraction idempotent
- **WHEN** `extract_and_store_for_session(sid)` is called twice for the same session
- **THEN** no duplicate rows appear in `topic_facts` (PRIMARY KEY conflict silently ignored)

### Requirement: Inline extraction triggers after save_session

The system SHALL call `extract_and_store_for_session(sid, candidate_id)` immediately after `save_session` returns, so the cache reflects the just-completed interview before the UI rerun.

#### Scenario: Cache updated after first save_session
- **WHEN** a user completes their first interview and `_generate_report()` calls `save_session(...)` which returns `sid`
- **THEN** `candidate_topic_cache` for `candidate_id="default"` contains at least one row from that session's turns (assuming thresholds met)

#### Scenario: Subsequent session updates cache (not replaces)
- **WHEN** a second interview completes and writes topics overlapping with the first
- **THEN** overlapping topic rows have their `score` updated via UPSERT (or recomputed) and `last_seen_at` advanced; new topics are inserted; vanished topics may stay (acceptable staleness for MVP)

### Requirement: Failure isolation — extract error does not block save or UI

The system SHALL wrap the `extract_and_store_for_session` call in `try/except Exception` and silently log to `data/error.log` on failure, so a topic-extraction bug never blocks session persistence or user-visible UI.

#### Scenario: Extraction failure does not raise
- **WHEN** `extract_and_store_for_session(sid)` raises `RuntimeError` (simulated in test)
- **THEN** the call site does NOT propagate; `_generate_report()` continues; UI rerun completes; error is appended to `data/error.log`

#### Scenario: Save still succeeds when extract fails
- **WHEN** extract raises but save completed before extract was called
- **THEN** `interview_sessions` row exists; `interview_turns` rows exist; only `topic_facts` / `candidate_topic_cache` writes are missing

### Requirement: Sidebar UI shows topic cloud + trend chart inside collapsed expander

The system SHALL render a sidebar expander titled `🎯 跨会话训练图谱` (default `expanded=False`, matching v0.3 UX 收口 pattern) that, when expanded, displays:
1. **Topic cloud**: top-N topics as HTML `<span>` chips whose `font-size` is `12 + score * 24` (linear mapping, score 0..1 → 12..36px), colored emerald for top-third, default gray for the rest.
2. **Trend chart**: `st.bar_chart` showing top-10 topics by x-axis and average `score` (0..1) on y-axis, with x-axis labels rotated 45°.
3. **Per-topic trend list (Phase 2)**: below the bar chart, render `st.caption("🔍 按主题查趋势(点击展开):")` followed by one `st.button` per topic in `get_topics_for_candidate(...)` (button label prefixes `▶` when collapsed, `▼` when expanded). Clicking a button toggles `st.session_state["trend_open_topic"]` to that topic (or back to `None` if that topic was already open) and calls `st.rerun()`. When `trend_open_topic` is set, render `st.line_chart` with `get_topic_trend(candidate_id, topic)` mapped as `score` (y-axis, 0..1) over `ended_at` (x-axis, truncated to ISO date prefix `[:10]`). If `len(trend) < 2`, show `st.caption(f"⚠️ 仅 {len(trend)} 场会话,需要 ≥ 2 场才能画趋势。")` instead of a chart. Trend data is fetched lazily on click (no per-render aggregation query).

#### Scenario: Expander present in sidebar
- **WHEN** the app is running and the user opens the sidebar
- **THEN** an expander titled `🎯 跨会话训练图谱` exists in `expanded=False` state

#### Scenario: Empty cache shows empty state message
- **WHEN** `candidate_topic_cache` for `candidate_id="default"` has 0 rows
- **THEN** the expander body shows `st.caption("暂无跨 session 数据,完成第 2 场后会自动出现。")` instead of charts

#### Scenario: Populated cache shows cloud + chart
- **WHEN** `candidate_topic_cache` has ≥ 1 row
- **THEN** the expander body renders the topic cloud (HTML chips with variable font-size) and the trend bar chart

#### Scenario: Topic cloud font-size scales with score
- **WHEN** topic A has score 0.9 and topic B has score 0.3
- **THEN** topic A's `<span>` has `font-size: ~33.6px` and topic B's `<span>` has `font-size: ~19.2px` (linear mapping)

#### Scenario: Per-topic trend button click toggles and renders line chart
- **WHEN** cache is populated and the user clicks the trend button for topic `"redis"` (which has 3 sessions in `topic_facts`)
- **THEN** `st.session_state["trend_open_topic"]` becomes `"redis"`; on rerun the expander body renders `st.line_chart` over `get_topic_trend(...)`'s score-vs-date data; the `"redis"` button label prefix flips from `▶` to `▼`

#### Scenario: Clicking the open topic again closes the chart
- **WHEN** the user clicks the currently-open topic's button a second time
- **THEN** `st.session_state["trend_open_topic"]` becomes `None`; on rerun the line chart is gone and the button label prefix returns to `▶`

#### Scenario: Topic with fewer than 2 sessions shows caption instead of chart
- **WHEN** `trend_open_topic="cache"` and `get_topic_trend` returns only 1 row
- **THEN** the expander body shows `st.caption(f"⚠️ 仅 1 场会话,需要 ≥ 2 场才能画趋势。")` instead of `st.line_chart`

### Requirement: Read API exposes per-candidate topics and per-topic trend

The system SHALL expose `get_topics_for_candidate(candidate_id) -> list[TopicFact]` (sorted by `score DESC, topic ASC`) and `get_topic_trend(candidate_id, topic) -> list[(session_id, score, ended_at)]` for any UI or programmatic consumer.

#### Scenario: Topics sorted deterministically
- **WHEN** `get_topics_for_candidate("default")` is called with 3 rows having scores `[0.5, 0.9, 0.5]` and topics `["A", "B", "C"]`
- **THEN** returned order is `["B" (0.9), "A" (0.5), "C" (0.5)]` — score DESC then topic ASC tiebreak

#### Scenario: Topic trend returns per-session timeline
- **WHEN** topic `"分布式锁"` appears in 2 sessions
- **THEN** `get_topic_trend("default", "分布式锁")` returns 2 rows, each `(session_id, score, ended_at)`, ordered by `ended_at ASC`

#### Scenario: Unknown topic returns empty trend
- **WHEN** topic `"never_appeared"` was never extracted
- **THEN** `get_topic_trend` returns `[]` (not raise)

