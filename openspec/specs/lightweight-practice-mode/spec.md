# lightweight-practice-mode Specification

## Purpose
TBD - created by archiving change 2026-07-27-add-practice-mode. Update Purpose after archive.
## Requirements
### Requirement: Menu has dedicated practice page

The system SHALL render a 4th page in `st.navigation` titled `专项练习`
(icon `🎯`), implemented at `pages/practice.py`. The page SHALL
provide a topic text input (placeholder `输入要练习的主题,例:kafka
高可用`) and a primary button `🎯 启动专项练习` (disabled while
topic is empty). The page SHALL also display the global
`interview_level` selectbox and `interview_style` radio for
consistency with the config page, but SHALL NOT display a JD text
area or a resume uploader (neither is required for practice).

#### Scenario: User opens practice page

- **WHEN** the user clicks `专项练习` in the sidebar navigation
- **THEN** `pages/practice.py` renders, the topic input is empty, and
  the start button is `disabled=True`

#### Scenario: User fills topic and starts

- **WHEN** the user enters `kafka 高可用` and clicks the start button
- **THEN** `st.session_state.practice_mode` is set to `True`,
  `st.session_state.practice_topic` is set to the stripped topic,
  `pending_start` is `True`, and the app navigates to the interview
  page

### Requirement: Practice mode ignores JD and resume

When `st.session_state.practice_mode` is `True`, the system SHALL NOT
pass the stored `jd_content` or treat it as a required input to the
interviewer system prompt, the report prompt, the authenticity
aggregator, or the persisted session row. If `resume_content` is
non-empty, it MAY be passed in as cross-validation context, but
practice SHALL NOT require it.

#### Scenario: Practice auto-start with empty JD

- **WHEN** the user starts a practice session with `jd_content=""` and
  no resume
- **THEN** the interviewer system prompt contains no `【目标岗位 JD】`
  section and no `【候选人简历】` section, and the first assistant
  message targets the practice topic without asking for a self-
  introduction

#### Scenario: Practice session persisted

- **WHEN** a practice session ends and the report is saved
- **THEN** the `interview_sessions` row has `mode='practice'`

### Requirement: Practice prompt forbids asking for JD or resume

When `focus_context` is non-None, the interviewer system prompt SHALL
include core rules that:
- (rule 3) forbid the interviewer from requesting the candidate's
  resume, work history, or job background
- (rule 4) forbid the interviewer from asking or assuming which role
  the candidate is applying for

The legacy wording "严格对齐 JD 要求的技能" and "优先针对候选人简历中
提到的项目" SHALL NOT appear when `focus_context` is non-None.

#### Scenario: Practice prompt has the right core rules

- **WHEN** `build_interviewer_system_prompt` is called with
  `focus_context="kafka 高可用"`
- **THEN** the prompt contains `禁止索要简历` and
  `禁止询问或假设候选人应聘什么岗位`, and does NOT contain
  `严格对齐 JD 要求的技能`

### Requirement: Practice report uses topic mastery dimension

The system MUST use topic mastery as the first report dimension for
practice sessions. Concretely, when `build_report_prompt` is called
with non-None `focus_context`:
- the prompt MUST omit the `【目标岗位 JD】` header block
- replace dimension 1 (`岗位匹配度`) with
  `主题掌握度(对「{focus_context}」的理解深度与完整度)`
- write `练习主题:{focus_context}` in the basic-info block instead of
  `目标岗位(从 JD 提炼)`
- append a hard constraint `不评岗位匹配` to the report's hard
  constraints

The legacy 7-dimension structure remains unchanged for non-practice
sessions.

#### Scenario: Practice report prompt

- **WHEN** `build_report_prompt` is called with
  `focus_context="kafka 高可用"`, empty JD, empty resume
- **THEN** the prompt contains `主题掌握度`, contains
  `练习主题:kafka 高可用`, and does NOT contain
  `目标岗位(从 JD 提炼)`

### Requirement: History list marks practice sessions

The system MUST distinguish practice sessions in the report page
history list. Concretely, when listing sessions in the report page
history segment, the system SHALL prepend `🎯 练习 · ` to the button
label for any session whose `mode` column equals `'practice'`. The
system MUST NOT add the prefix to normal interview sessions.

#### Scenario: Mixed history rendering

- **WHEN** the history list contains one practice session and one
  normal session
- **THEN** the practice session's button label starts with
  `🎯 练习 · `, and the normal session's button label does not

