## 1. Topic extraction module

- [x] 1.1 Create `topic_extraction.py` with `TopicFact(topic: str, score: float, source_turn: int)` frozen dataclass
- [x] 1.2 Implement `_tokenize_cjk_2gram(text: str) -> list[str]` (CJK char `[一-鿿]+` → sliding window size 2; `[a-zA-Z0-9]+` → whitespace-split; min length 2 filter)
- [x] 1.3 Define `_STOPWORDS` (~80 Chinese + ~30 English stopwords) and `_PII_PATTERNS` (~6 regex patterns: 公司 / 集团 / LLC / Inc / Corp / Co. / 有限公司 / project codename)
- [x] 1.4 Implement `_mask_pii(text: str) -> str` (substitute PII entities with ` ` before tokenize; case-insensitive for English)
- [x] 1.5 Define `_SYNONYM_MAP` (~50 entries: 性能/perf/performance → performance, HA/高可用/high_availability → high_availability, QPS/tps → throughput, etc.)
- [x] 1.6 Implement `_apply_synonyms(tokens: list[str]) -> list[str]` (replace each token via SYNONYM_MAP; pass-through if no entry)
- [x] 1.7 Implement `_compute_tf(tokens: list[str]) -> dict[str, int]` (Counter wrapper)
- [x] 1.8 Implement `_filter_by_thresholds(tf: dict[str, int], total: int, min_tf: int = 3, min_ratio: float = 0.05) -> list[tuple[str, int]]`
- [x] 1.9 Implement `extract_topics(turns: list[dict], *, min_tf: int = 3, min_ratio: float = 0.05) -> list[TopicFact]` (per-turn pipeline: mask → tokenize → synonym fold → first-seen index → tf → filter → score)
- [x] 1.10 Add module docstring covering the pipeline + zero-LLM cost guarantee

## 2. Storage extension

- [x] 2.1 Add `topic_facts` and `candidate_topic_cache` CREATE TABLE statements to `storage.SCHEMA` (PRIMARY KEYs as in spec §"Dual-table storage schema")
- [x] 2.2 Implement `write_topic_facts(db_path, sid, topics: list[TopicFact])` using `INSERT OR IGNORE`
- [x] 2.3 Implement `write_candidate_topic_cache(db_path, candidate_id, topics: list[TopicFact], last_seen_at: datetime)` using UPSERT (`INSERT ... ON CONFLICT(candidate_id, topic) DO UPDATE SET score=excluded.score, last_seen_at=excluded.last_seen_at`)
- [x] 2.4 Implement `get_topics_for_candidate(db_path, candidate_id) -> list[TopicFact]` (SELECT all rows ordered by `score DESC, topic ASC`)
- [x] 2.5 Implement `get_topic_trend(db_path, candidate_id, topic: str) -> list[tuple[str, float, str]]` (JOIN with `interview_sessions` for `ended_at`, ordered by `ended_at ASC`)
- [x] 2.6 Implement `extract_and_store_for_session(db_path, sid, candidate_id) -> int` (orchestrator: `get_session` → `extract_topics` → `write_topic_facts` + `write_candidate_topic_cache` in one transaction; return topics written count)
- [x] 2.7 Verify `init_db()` is idempotent against a pre-existing v0.3 database (existing 4 tables untouched)

## 3. Tests for topic extraction

- [x] 3.1 Create `tests/test_topic_extraction.py` with shared fixtures (sample turns for CJK / English / mixed / empty)
- [x] 3.2 Test `_tokenize_cjk_2gram`: pure Chinese → 2-grams; pure English → whitespace tokens; mixed → both
- [x] 3.3 Test `_mask_pii`: strips `公司`/`集团`/`LLC`/`Inc`/`Corp` (case-insensitive) and multi-word entity names like `Acme Corp`
- [x] 3.4 Test `_apply_synonyms`: folds `性能`/`perf`/`performance` → `performance`; preserves unmapped tokens
- [x] 3.5 Test `_filter_by_thresholds`: min_tf cutoff, min_ratio cutoff, both-passing case, both-failing case
- [x] 3.6 Test `extract_topics` happy path: 10+ turn sample produces ≥ 3 topics with score in `[0, 1]`
- [x] 3.7 Test `extract_topics` edge cases: empty list → `[]`; all-empty-content → `[]`; single-turn → may produce 0 or 1 topic depending on thresholds
- [x] 3.8 Test that PII entities never appear in returned topic strings (sample with `FooCorp` + `Bar Inc` → no `FooCorp`/`Bar`/`Inc` in output)
- [x] 3.9 Performance test: 30 turns × 200 words each completes in <500ms

## 4. Tests for storage extension

- [x] 4.1 Create `tests/test_storage_topics.py` with tmp_path DB fixture
- [x] 4.2 Test `init_db` creates both new tables; pre-existing tables untouched
- [x] 4.3 Test `write_topic_facts` idempotency: second call with same `(sid, topic, source_turn)` does not duplicate
- [x] 4.4 Test `write_candidate_topic_cache` UPSERT: same topic inserted twice updates score + last_seen_at
- [x] 4.5 Test `get_topics_for_candidate` sort order: score DESC tiebreak topic ASC
- [x] 4.6 Test `get_topic_trend` per-session ordering: ended_at ASC; missing topic returns `[]`
- [x] 4.7 Test `extract_and_store_for_session` end-to-end: insert session + turns → call → verify both tables populated
- [x] 4.8 Test failure isolation: if `extract_topics` raises, `extract_and_store_for_session` returns 0 and does NOT raise (caller can swallow)

## 5. App.py integration

- [x] 5.1 Import `extract_and_store_for_session` from `storage` in `app.py`
- [x] 5.2 In `_generate_report()`, after successful `save_session` returns `sid`, wrap `extract_and_store_for_session(None, sid, get_candidate_id())` in `try/except Exception`; on failure append to `data/error.log` (reuse `_ERROR_LOG_PATH` from existing handler)
- [x] 5.3 Add `topic_cloud_html(topics: list[TopicFact]) -> str` helper in `app.py` (linear font-size mapping `12 + score * 24`; emerald for top-third, gray for rest; `html.escape` all topic strings)
- [x] 5.4 In sidebar (after existing `st.divider()` for history), add `st.expander("🎯 跨会话训练图谱", expanded=False)` block:
  - Fetch `topics = get_topics_for_candidate(None, get_candidate_id())` inside try/except (empty list on error)
  - If empty: `st.caption("暂无跨 session 数据,完成第 2 场后会自动出现。")`
  - Else: `st.markdown(topic_cloud_html(topics), unsafe_allow_html=True)` then `st.bar_chart({"score": [t.score for t in topics[:10]]})` with labels `[t.topic for t in topics[:10]]`

## 6. AppTest integration tests

- [x] 6.1 Create `tests/test_app_topics.py` (AppTest-based, mirroring `tests/test_app.py` patterns)
- [x] 6.2 Test expander present in sidebar on app load (search rendered tree for `🎯 跨会话训练图谱`)
- [x] 6.3 Test empty state: with fresh DB, expander body shows empty caption (no chart rendered)
- [x] 6.4 Test populated state: pre-populate `candidate_topic_cache` via direct DB write, then verify cloud + chart render
- [x] 6.5 Test extract hook fires on save_session: mock `extract_and_store_for_session`, run an end-to-end interview, verify called once with correct `sid` + `candidate_id`
- [x] 6.6 Test extract failure does not break interview flow: mock `extract_and_store_for_session` to raise, verify session persists + report renders + no exception bubbles

## 7. Verification

- [x] 7.1 Run full test suite: `uv run pytest tests/ -v` (target: 242 prior + ~35 new = ~277 all green)
- [ ] 7.2 Run manual smoke: `streamlit run app.py`, complete 2 interviews, verify sidebar expander populates with topic cloud + bar chart after second interview
- [ ] 7.3 Run manual smoke for PII: complete interview mentioning a real company name; verify that company name does NOT appear in topic cloud
- [x] 7.4 Verify backwards compat: load a v0.3-era DB, run `init_db()`, confirm 4 existing tables + 2 new tables all present, existing session/turn data intact
- [x] 7.5 Update memory file `project_baozi_streamlit_mvp.md` with `v0.3 Feature F: 跨会话记忆可视化` summary (replacing stale `web/`/`evals/` references if any remain)