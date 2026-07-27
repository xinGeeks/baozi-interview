# multipage-navigation Specification

## Purpose
TBD - created by archiving change add-multipage-navigation. Update Purpose after archive.
## Requirements
### Requirement: App exposes a 4-page linear navigation via `st.navigation`

The system MUST use Streamlit's `st.navigation` API to expose exactly 4 pages, in this order:
1. **配置** (config) — file_uploader for 简历 PDF, text_area for JD, selectbox for 职级 (LEVELS), radio for 风格 (STYLES), and a primary "🚀 开始面试" button.
2. **面试** (interview) — chat_message loop (assistant / user turns), per-turn feedback cards, chat_input (with END_SIGNAL keyword support), and the existing `🚪 退出专项训练` button when in practice mode.
3. **报告** (report) — segmented control to switch between "本场报告" and "历史报告" (history read-only view of a saved session), including Markdown download button.
4. **训练图谱** (topics) — `🎯 跨会话训练图谱` expander (topic cloud + Top-10 bar + per-topic trend list) and `🎯 弱 topic 专项练习` expander (top-8 candidate buttons).

The `app.py` entry point MUST call `st.navigation([Page("pages/config.py", ...), Page("pages/interview.py", ...), Page("pages/report.py", ...), Page("pages/topics.py", ...)])` (or equivalent `st.Page(...)` list). Each page's module file lives under `pages/` and is auto-discoverable.

#### Scenario: Navigation menu shows 4 entries

- **WHEN** the user opens the running app
- **THEN** the navigation menu (rendered by `st.navigation` default UI) shows exactly 4 entries: 配置 / 面试 / 报告 / 训练图谱

#### Scenario: Each page renders its core widget set

- **WHEN** the user navigates to a page
- **THEN** that page renders the widgets described in its requirement (config: file_uploader + text_area + selectbox + radio + start button; interview: chat_message loop + chat_input; report: segmented control + report body; topics: 2 expanders)

#### Scenario: Each page is a separate module file

- **WHEN** the project is inspected
- **THEN** `pages/config.py`, `pages/interview.py`, `pages/report.py`, `pages/topics.py` exist and `app.py` does NOT contain the page-specific rendering code

### Requirement: Auto-advance to the next page on completion

The system MUST auto-navigate to the next page when the user completes a step:
- From **配置** to **面试** when the user clicks the primary "🚀 开始面试" button (after `_start_interview` succeeds) → `st.switch_page("pages/interview.py")` (or equivalent).
- From **面试** to **报告** when `_generate_report` finishes (e.g., END_SIGNAL or 🚪 退出专项训练 triggers it) → `st.switch_page("pages/report.py")`.

The system MUST NOT auto-navigate from **报告** — the user explicitly clicks either "下一场" (→ 配置) or "查看训练图谱" (→ 训练图谱) to leave.

#### Scenario: Start interview advances to interview page

- **WHEN** the user fills JD, clicks "🚀 开始面试", and `_start_interview` succeeds
- **THEN** the current page is `pages/interview.py` (verified by `st.session_state.current_page == "interview"` or equivalent marker)

#### Scenario: END_SIGNAL advances to report page

- **WHEN** `interview_started=True`, the user submits an answer containing `END_SIGNAL`, and `_generate_report` finishes
- **THEN** the current page becomes `pages/report.py` and the report body is rendered

#### Scenario: Practice exit advances to report page

- **WHEN** `practice_mode=True` and the user clicks "🚪 退出专项训练" or submits an answer containing "退出专项训练"
- **THEN** `_generate_report` is invoked, `mode='practice'` is persisted, and the current page becomes `pages/report.py`

#### Scenario: Report page does NOT auto-advance

- **WHEN** the user is on `pages/report.py` with `report_text` rendered
- **THEN** the user remains on `pages/report.py` until they click an explicit "下一场" or "查看训练图谱" button (no timer-based navigation)

### Requirement: Sidebar is global and only shows data deletion

The system MUST keep the sidebar global across all 4 pages and only render these items:
- A "🗑️ 清空我的全部历史" button (inside a confirmation expander, mirroring the existing pattern in `app.py`).

The sidebar MUST NOT render the legacy history list, the 跨会话训练图谱 expander, or the 弱 topic 专项练习 expander — those are moved into the corresponding pages.

There is no ToS gate (personal project; ToS/隐私系统已移除)。

#### Scenario: Sidebar shows only global items

- **WHEN** the user is on any of the 4 pages
- **THEN** the sidebar contains only the 清空我的全部历史 button (verified by absence of `🎯 跨会话训练图谱` and `🎯 弱 topic 专项练习` expander labels in sidebar)

#### Scenario: All 4 pages accessible without gate

- **WHEN** the app starts
- **THEN** `app.py` calls `st.navigation` directly without any `st.stop()` gate; the default page renders immediately

### Requirement: History read-only view is integrated into the report page

The system MUST provide a way to view historical sessions (interview or practice) without leaving the report page. The report page MUST include a segmented control (or equivalent widget) with at least 2 options:
- **本场报告** — shows the current `st.session_state.report_text` (the just-completed interview or practice session).
- **历史报告** — shows a selectable list of historical sessions (from `list_sessions(None, candidate_id)`) and renders the selected session's turns + feedback + report_text read-only via `_render_history_view(session_id)`.

When the user clicks a historical session in any other page (config sidebar history button, topics page history list, or direct link), the system MUST set `st.session_state.loaded_session_id` and `viewing_history = True`, then `st.switch_page("pages/report.py")` to land on the report page in history-view mode.

#### Scenario: Report page shows current report by default

- **WHEN** the user arrives at `pages/report.py` after completing a fresh interview and `st.session_state.report_text` is non-empty
- **THEN** the page renders the current `report_text` as Markdown (with download button) and `st.session_state.viewing_history` is `False`

#### Scenario: History list renders under "历史报告" segment

- **WHEN** the user switches the report-page segmented control to "历史报告"
- **THEN** the page shows a list of past sessions (each row: `ended_at[:10] · level · turn_count 轮`); selecting one renders that session's turns + feedback + report_text in read-only mode

#### Scenario: Click history from topics page navigates to report

- **WHEN** the user clicks a historical session button in `pages/topics.py` (e.g., a "查看历史" section there)
- **THEN** `loaded_session_id` and `viewing_history=True` are set, the user is on `pages/report.py`, and the page renders the selected session in read-only mode

### Requirement: Weak-topic practice entry from topics page reuses interview chat loop

The system MUST integrate the existing `practice_mode` state machine into the topics page: when the user clicks a topic candidate button in the `🎯 弱 topic 专项练习` expander on `pages/topics.py`, the system MUST set `st.session_state.practice_mode = True` and `practice_topic = <topic>`, then `st.switch_page("pages/interview.py")`. The interview page MUST auto-start a focused interview via the existing auto-start trigger (Feature G), which calls `_start_interview()` with the `focus_context` prompt injection from `build_interviewer_system_prompt(..., focus_context=practice_topic)`.

The system MUST keep the existing `🚪 退出专项训练` button and "退出专项训练" text signal behavior (Feature G) — they continue to work in the new multipage layout because they share the same `st.session_state` and the same `_handle_user_answer` / `_generate_report` functions.

#### Scenario: Click candidate button on topics page enters practice

- **WHEN** the user clicks a `📍 <topic>` button in the practice expander on `pages/topics.py`
- **THEN** `st.session_state.practice_mode` is `True`, `practice_topic` is the clicked topic, and the current page becomes `pages/interview.py` with `interview_started=True` and the chat_input rendered (auto-start fired)

#### Scenario: Practice transcript is saved with mode='practice'

- **WHEN** the user exits the practice via the exit button or text signal on `pages/interview.py`
- **THEN** `_generate_report` is called, `save_session(..., mode="practice")` persists the row, and `extract_and_store_for_session` does NOT write to `candidate_topic_cache` (the Feature G gate is preserved)

#### Scenario: Practice exit advances to report page in practice mode

- **WHEN** the user exits practice from the interview page
- **THEN** the current page becomes `pages/report.py` and the report body shows the practice session's report (still rendering the just-finished practice report under "本场报告")

