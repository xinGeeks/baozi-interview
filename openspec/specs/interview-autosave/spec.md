# interview-autosave Specification

## Purpose
TBD - created by archiving change add-interview-autosave. Update Purpose after archive.
## Requirements
### Requirement: In-progress interview is autosaved to a draft slot

The system MUST persist an in-progress interview to a single-row-per-candidate draft slot (`interview_autosave` table, keyed by `candidate_id`) so that the interview survives a browser refresh (which starts a fresh Streamlit session and clears `session_state`).

The draft MUST be written whenever the interview advances a turn — specifically at the end of `_start_interview()` (after the first question is generated) and at the end of `_handle_user_answer()` (after each answer, whether or not a next question is generated). The autosave MUST be best-effort: a persistence failure MUST be logged and MUST NOT block the interview UI.

The draft `state_json` MUST include everything needed to fully resume, including the resume text: `chat_history`, `turn_feedback`, `turn_authenticity_flags`, `interview_level`, `interview_style`, `jd_content`, `resume_content`, `practice_mode`, `practice_topic`, and `interview_started_at`.

The autosave MUST only occur while the interview is active (`interview_started` true, `interview_ended` false, `viewing_history` false).

#### Scenario: Answering a turn writes the draft

- **WHEN** an interview is in progress and the user submits an answer
- **THEN** an `interview_autosave` row for the current `candidate_id` exists with a `state_json` whose `chat_history` matches the current conversation

#### Scenario: Autosave failure does not break the interview

- **WHEN** the autosave write raises an exception
- **THEN** the interview continues rendering normally and the error is appended to the error log

### Requirement: Refresh restores the in-progress interview

The system MUST detect an existing draft on the config page and the interview page and offer to resume it. When a draft exists AND the current session has no active interview (`interview_started` is false), the page MUST render a "继续未完成的面试" prompt showing the saved turn count, with a "继续面试" action and a "放弃草稿" action.

Choosing "继续面试" MUST restore the draft into `session_state` (including `resume_content`), set `interview_started=True` / `interview_ended=False` / `viewing_history=False`, and land the user on the interview page. Choosing "放弃草稿" MUST delete the draft and remove the prompt.

#### Scenario: Draft surfaces after refresh

- **WHEN** a draft exists and a fresh session loads the config page with no active interview
- **THEN** a resume prompt is shown with the saved turn count and 继续/放弃 controls

#### Scenario: Continue restores the conversation

- **WHEN** the user clicks "继续面试"
- **THEN** `interview_started` is `True`, `chat_history` (and `resume_content`) are restored from the draft, and the interview page renders the conversation with a chat input

#### Scenario: Discard removes the draft

- **WHEN** the user clicks "放弃草稿"
- **THEN** the `interview_autosave` row is deleted and no resume prompt is shown on reload

#### Scenario: Active session is not interrupted

- **WHEN** an interview is already active in the current session (`interview_started` is true)
- **THEN** the resume prompt MUST NOT render (navigating between pages does not re-offer resume)

### Requirement: Completing an interview clears the draft

The system MUST delete the draft slot for the current candidate after a report is successfully generated and the completed session is persisted via `save_session` in `_generate_report()`.

#### Scenario: Report generation clears the draft

- **WHEN** `_generate_report()` completes and persists the session
- **THEN** the `interview_autosave` row for the current `candidate_id` no longer exists

#### Scenario: No resume prompt after completion

- **WHEN** an interview has been completed and the app is reloaded
- **THEN** no resume prompt is shown (the draft was cleared)

