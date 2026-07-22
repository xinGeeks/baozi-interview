# authenticity-detection Specification

## Purpose
TBD - created by archiving change add-authenticity-detection. Update Purpose after archive.
## Requirements
### Requirement: Per-turn heuristic signal detection

The system SHALL run `detect_signals(question, answer, resume_text)` after each user answer and return a list of zero or more signal flags from this fixed vocabulary: `["过于简短", "模板化", "答非所问", "未引用简历"]`.

#### Scenario: Empty flags for clean answer
- **WHEN** user gives a 30-word answer with specific metrics and at least one question keyword overlap
- **THEN** `detect_signals` returns `[]`

#### Scenario: Too-short answer flagged
- **WHEN** user answer has < 8 words and is not a question
- **THEN** `detect_signals` includes `"过于简短"` in returned list

#### Scenario: Boilerplate phrase without numbers flagged
- **WHEN** user answer contains generic phrase like "很多东西" or "比较熟悉" and contains no digits
- **THEN** `detect_signals` includes `"模板化"` in returned list

#### Scenario: Off-topic answer flagged
- **WHEN** question mentions "高并发" but answer contains zero overlapping keywords after stopword removal
- **THEN** `detect_signals` includes `"答非所问"` in returned list

#### Scenario: Resume-free answer flagged when resume is non-empty
- **WHEN** resume contains "订单系统" and answer mentions none of the resume's project names or tech stack terms
- **THEN** `detect_signals` includes `"未引用简历"` in returned list

### Requirement: Heuristic runs in <1ms

The system SHALL execute `detect_signals` synchronously in <1ms for any answer ≤ 1000 words on a typical machine.

#### Scenario: Performance budget
- **WHEN** `detect_signals` is invoked with a 200-word answer
- **THEN** execution completes in <1ms (measured in test)

### Requirement: Report-time LLM authenticity aggregation

The system SHALL issue one LLM call at report generation time with `(resume_text, jd, chat_history, all_turn_flags)` and parse the response into `AuthenticityReport { score: float 0..1, findings: list[Finding], summary: str }`.

#### Scenario: Clean transcript produces perfect score
- **WHEN** all turn_flags are empty across the interview
- **THEN** parsed `score == 1.0` and `findings == []`

#### Scenario: Flagged turns produce sub-1.0 score with grounded findings
- **WHEN** at least one turn has flags and the LLM responds with `{"score": 0.65, "findings": [{"turn": 3, "issue": "答非所问", "detail": "..."}], "summary": "..."}`
- **THEN** parsed `AuthenticityReport.score == 0.65` and `findings` contains the parsed objects

#### Scenario: Out-of-range score is clamped
- **WHEN** LLM responds with `{"score": 1.5, ...}`
- **THEN** parsed score is clamped to `1.0`

#### Scenario: Parse failure returns sentinel
- **WHEN** LLM response cannot be parsed (missing required keys or malformed JSON)
- **THEN** `parse_authenticity_response` returns a sentinel `AuthenticityReport(score=-1.0, findings=[], summary="LLM 解析失败")` instead of raising

### Requirement: LLM aggregation prompt constrains to given signals

The system SHALL include in `build_authenticity_judgment_prompt` the instruction: "只基于 given signals 推断,不得编造未在 signals 中出现的事实;若 signals 为空,score 必须是 1.0 且 findings 必须是空列表".

#### Scenario: Prompt contains hard constraint
- **WHEN** `build_authenticity_judgment_prompt` is called with empty signals
- **THEN** returned prompt string contains the substring "只基于 given signals"

### Requirement: Per-turn UI shows authenticity warning when flags exist

The system SHALL display a `⚠️` indicator with the first flag text on the per-turn feedback card when `turn_authenticity_flags` is non-empty; SHALL NOT display any indicator when the list is empty.

#### Scenario: Card shows warning when flagged
- **WHEN** `turn_authenticity_flags == ["答非所问"]`
- **THEN** the rendered feedback card markdown contains `⚠️` and `答非所问`

#### Scenario: Card omits warning when clean
- **WHEN** `turn_authenticity_flags == []`
- **THEN** the rendered feedback card markdown does NOT contain `⚠️`

### Requirement: Report renders section 7 when authenticity_report exists

The system SHALL render a "第 7 段 · 真实性维度" section in the final report when `authenticity_report.score >= 0`; SHALL hide the section when score is the sentinel `-1.0`.

#### Scenario: Section rendered with valid score
- **WHEN** `authenticity_report.score == 0.7` and `findings` is non-empty
- **THEN** the rendered report markdown contains a heading with "真实性" and the findings listed

#### Scenario: Section hidden on parse failure
- **WHEN** `authenticity_report.score == -1.0`
- **THEN** the rendered report markdown does NOT contain a "真实性" section heading

### Requirement: All new fields are backward-compatible optional

The system SHALL default `turn_authenticity_flags` to `[]` and `authenticity_report` to `None` when not provided, and existing v0.3 feedback/report tests SHALL continue to pass without modification.

#### Scenario: Defaults preserve legacy behavior
- **WHEN** `_handle_user_answer` is called without a pre-computed `turn_authenticity_flags` value
- **THEN** `st.session_state["turn_authenticity_flags"]` defaults to `[]` and `_render_feedback_card` does not raise

