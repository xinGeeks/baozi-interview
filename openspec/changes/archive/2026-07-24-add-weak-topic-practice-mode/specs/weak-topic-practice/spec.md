## ADDED Requirements

### Requirement: Sidebar exposes practice entry from top-frequency topics

The system SHALL render a sidebar expander titled `🎯 弱 topic 专项练习` (default `expanded=False`, matching v0.3 UX 收口 pattern) that, when expanded, displays the top-8 entries from `get_topics_for_candidate(candidate_id)` (sorted by `score DESC, topic ASC`) as one button per topic. Each button's label is `📍 <topic>` and clicking it sets `st.session_state.practice_mode = True` and `st.session_state.practice_topic = <topic>`, then triggers `st.rerun()`.

The expander body MUST show a caption explaining that cache.score is *frequency share* (not mastery), so users understand the ranking basis. When the candidate's `candidate_topic_cache` is empty, the body MUST show `st.caption("📭 暂无候选主题。先完成 1-2 场面试,主题出现在『跨会话训练图谱』后再来。")` instead of any button.

#### Scenario: Practice expander present and labeled

- **WHEN** the app is running and the user opens the sidebar
- **THEN** an expander titled `🎯 弱 topic 专项练习` exists in `expanded=False` state

#### Scenario: Empty cache shows empty state caption

- **WHEN** `candidate_topic_cache` for `candidate_id="default"` has 0 rows
- **THEN** the expander body shows the empty-state caption instead of any topic button

#### Scenario: Populated cache shows top-8 candidate buttons

- **WHEN** `candidate_topic_cache` has ≥ 1 row
- **THEN** the expander body renders up to 8 buttons, one per topic, in `score DESC, topic ASC` order

### Requirement: Focused chat loop injects a practice block into the system prompt

The system SHALL set `st.session_state.practice_mode = True` after the user clicks a candidate button, and on the next `at.run()` the auto-start trigger fires `_start_interview()` which constructs the LLM `system` message via `build_interviewer_system_prompt(level, style, resume, jd, focus_context=practice_topic)`. The prompt extension MUST inject a `[专项训练模式]` block at the end of the system prompt (before the opening line) that contains the focus topic and instructs the LLM to drill into it (基础概念 → 典型场景 → 踩过的坑 → 与简历的交叉验证, re-link the focus topic at least every 3 turns).

#### Scenario: Practice auto-start sets session state

- **WHEN** the user clicks a candidate button for topic `"kafka"`
- **THEN** on the next rerun `st.session_state.practice_mode` is `True`, `practice_topic` is `"kafka"`, `interview_started` becomes `True`, and `at.chat_input` is rendered (auto-start trigger fired `_start_interview`)

#### Scenario: Practice mode skips JD non-empty validation

- **WHEN** `practice_mode` is `True` and `st.session_state.jd_content` is empty
- **THEN** `_start_interview()` does NOT set `error_msg = "请先粘贴 JD 再开始面试"` and proceeds to generate the first question

#### Scenario: focus_context appears in system prompt

- **WHEN** `_system_prompt()` is called with `practice_mode=True` and `practice_topic="kafka"`
- **THEN** the returned system prompt string contains the literal substring `[专项训练模式]` and `「kafka」`

### Requirement: Practice exit ends session and clears practice state

The system SHALL provide two equivalent exit paths from practice mode:
1. A `🚪 退出专项训练` button rendered in the main area (only when `practice_mode=True and interview_started=True and not interview_ended`).
2. The chat_input text signal `"退出专项训练"` — when present in the user's input, behaves like the existing `END_SIGNAL` flow.

Both paths MUST call `_generate_report()` (which calls `save_session` with `mode="practice"`) and then set `st.session_state.practice_mode = False` and `st.session_state.practice_topic = ""`, followed by `st.rerun()`.

#### Scenario: Exit button saves with practice mode and clears state

- **WHEN** `practice_mode=True`, `interview_started=True`, `interview_ended=False`, and the user clicks `🚪 退出专项训练`
- **THEN** `interview_sessions.mode` is `"practice"` for the new row; `practice_mode` becomes `False`; `practice_topic` becomes `""`

#### Scenario: Text signal exit path

- **WHEN** `practice_mode=True` and the user submits an answer containing the substring `"退出专项训练"`
- **THEN** `_generate_report()` is invoked; `interview_sessions.mode` for the new row is `"practice"`; `practice_mode` is reset to `False`

#### Scenario: Normal END_SIGNAL also exits practice (backward-compat)

- **WHEN** `practice_mode=True` and the user submits an answer containing the existing `END_SIGNAL` keyword
- **THEN** `_generate_report()` is invoked and the row is saved with `mode="practice"`; `practice_mode` is reset to `False` (text-signal reset still runs)

### Requirement: Practice sessions are stored separately and do not pollute the cross-session topic cache

The system SHALL persist practice sessions in `interview_sessions` with `mode='practice'` (default for new code paths) and SHALL ensure that `extract_and_store_for_session(db_path, sid, candidate_id)` writes zero rows to `candidate_topic_cache` when the row's `mode` is `"practice"`. The function MUST short-circuit internally (not delegate the check to the caller) so that any invocation path — app, CLI, test — gets the same isolation.

The system SHALL also support `list_sessions(db, candidate_id, *, mode=None)` where `mode=None` returns all sessions (backward-compat), `mode="interview"` returns only normal interview rows, and `mode="practice"` returns only practice rows.

#### Scenario: init_db adds mode column on legacy DBs

- **WHEN** `init_db(db)` is called on a database created by v0.3 (no `mode` column) and containing 1+ existing rows
- **THEN** `interview_sessions.mode` column exists; existing rows have `mode='interview'` (back-filled)

#### Scenario: save_session persists mode='practice'

- **WHEN** `save_session(..., mode='practice')` is called
- **THEN** `get_session(db, sid)['mode']` returns `'practice'`

#### Scenario: save_session default mode is 'interview'

- **WHEN** `save_session(...)` is called without the `mode` argument
- **THEN** `get_session(db, sid)['mode']` returns `'interview'` (backward-compat)

#### Scenario: extract_and_store_for_session skips practice sessions

- **WHEN** `extract_and_store_for_session(db, sid, candidate_id)` is called on a row with `mode='practice'`
- **THEN** the function returns `0` and `candidate_topic_cache` for the candidate is unchanged

#### Scenario: extract_and_store_for_session runs for interview sessions

- **WHEN** `extract_and_store_for_session(db, sid, candidate_id)` is called on a row with `mode='interview'` and content meeting thresholds
- **THEN** the function writes at least 1 row to `candidate_topic_cache` (control test confirming practice-mode gate does not regress interview flow)

#### Scenario: list_sessions filter by mode

- **WHEN** the database contains 1 interview row and 1 practice row
- **THEN** `list_sessions(db, "default", mode="interview")` returns 1 row with `mode='interview'`; `list_sessions(db, "default", mode="practice")` returns 1 row with `mode='practice'`; `list_sessions(db, "default")` (no mode arg) returns both rows

### Requirement: Sidebar history section shows a separate practice records subsection

The system SHALL split the existing `📚 历史面试` sidebar block into two views: the interview history (top, filtered by `mode='interview'`) and a new collapsible subsection titled `🎯 练习记录 (N)` (default `expanded=False`) that is rendered only when at least one `mode='practice'` row exists. The practice subsection MUST render each row as a clickable button with the same label format as the interview history (`<ended_at[:10]> · <level> · <turn_count> 轮`), and clicking it sets `st.session_state.loaded_session_id` and `viewing_history = True` (identical read-only view reuse).

#### Scenario: Practice subsection absent when zero practice rows

- **WHEN** `candidate_id='default'` has 0 `mode='practice'` rows
- **THEN** no `🎯 练习记录` expander is rendered in the sidebar

#### Scenario: Practice subsection rendered with N rows

- **WHEN** `candidate_id='default'` has ≥ 1 `mode='practice'` row
- **THEN** the sidebar contains a `🎯 练习记录 (N)` expander; expanding it shows the same per-row label + delete pattern as the interview history
