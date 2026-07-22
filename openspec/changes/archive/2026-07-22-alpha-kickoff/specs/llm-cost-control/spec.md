## ADDED Requirements

### Requirement: Char-Based Token Estimation
The system MUST estimate token usage from character count using a `len(text) // 4` heuristic, with no new dependencies.

#### Scenario: CJK content estimation
- **WHEN** a prompt contains 2000 Chinese characters
- **THEN** the estimated token count MUST be approximately 500 (±25%)

#### Scenario: Mixed content estimation
- **WHEN** a prompt contains 1000 Chinese characters and 400 English characters
- **THEN** the estimated token count MUST be approximately 350 (±25%)

#### Scenario: No new dependency
- **WHEN** the project is installed
- **THEN** `requirements.txt` MUST NOT add a tokenizer library (e.g., tiktoken)

### Requirement: Configurable Daily Token Budget
The system MUST read `LLM_DAILY_TOKEN_CAP` from the environment (or `.env`) and default to 200,000 when unset.

#### Scenario: Default cap applied
- **WHEN** `LLM_DAILY_TOKEN_CAP` is unset
- **THEN** the daily budget MUST be 200,000 tokens

#### Scenario: Custom cap applied
- **WHEN** `LLM_DAILY_TOKEN_CAP=500000` is set
- **THEN** the daily budget MUST be 500,000 tokens

#### Scenario: Cap zero disables enforcement
- **WHEN** `LLM_DAILY_TOKEN_CAP=0` is set
- **THEN** budget warnings and hard blocks MUST be suppressed

### Requirement: Soft Warning at 80% Budget
The system MUST show a yellow warning banner in the sidebar when the day's estimated token usage reaches 80% of the cap.

#### Scenario: Warning at threshold
- **WHEN** estimated usage reaches 80% of cap (e.g., 160,000 of 200,000)
- **THEN** the sidebar MUST display a warning banner: "⚠️ 已用 80% 今日预算"

#### Scenario: No warning below threshold
- **WHEN** estimated usage is below 80% of cap
- **THEN** no warning banner MUST be displayed

### Requirement: Hard Block at 100% Budget
The system MUST disable the user chat input and display a red banner when estimated daily token usage reaches 100% of the cap.

#### Scenario: Block at cap
- **WHEN** estimated usage reaches or exceeds 100% of cap
- **THEN** the chat input field MUST be disabled
- **AND** the sidebar MUST display a red banner: "❌ 今日预算已用完,明日 UTC 0 点重置"
- **AND** the resume upload and report generation MUST remain functional

#### Scenario: Manual override documented
- **WHEN** the user sees the cap-exceeded banner
- **THEN** the banner MUST mention that the cap can be raised via `LLM_DAILY_TOKEN_CAP` in `.env`

### Requirement: UTC Day Reset
The system MUST reset the daily token counter at UTC midnight (00:00 UTC), independent of the user's local timezone.

#### Scenario: Day boundary resets counter
- **WHEN** the local clock crosses UTC 00:00
- **THEN** the daily usage counter MUST be reset to zero
- **AND** budget enforcement MUST be re-enabled

#### Scenario: Timezone independent
- **WHEN** the user is in UTC+8 (Beijing) and the local time is 08:00 (UTC 00:00)
- **THEN** the daily counter MUST reset, regardless of the user's local timezone

### Requirement: Cost Estimation Documentation
The project MUST include a documentation file (`docs/llm-cost.md`) that estimates the LLM cost per interview and provides model selection guidance.

#### Scenario: Per-interview cost table
- **WHEN** a reader opens `docs/llm-cost.md`
- **THEN** the document MUST contain a table estimating tokens and cost for a typical 5-turn interview for each supported model

#### Scenario: Estimation disclaimer
- **WHEN** the document shows any cost number
- **THEN** the number MUST be labeled as an estimate with a ±25% margin
- **AND** the disclaimer MUST be visible on the same page

#### Scenario: Model selection guidance
- **WHEN** the reader wants to choose a model
- **THEN** the document MUST recommend a default and explain the trade-offs (cost vs. quality vs. latency)
