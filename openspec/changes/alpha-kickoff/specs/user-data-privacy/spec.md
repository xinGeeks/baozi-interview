## ADDED Requirements

### Requirement: PII Notice Before Resume Upload
The system MUST display a privacy notice in the sidebar before the user uploads a resume, stating that the original resume text is not persisted, that conversation data is stored in local SQLite, and that the user can delete their history.

#### Scenario: Notice visible on empty state
- **WHEN** the app loads and the user has not yet uploaded a resume
- **THEN** the sidebar MUST show a privacy notice with key facts (no resume text persisted, SQLite local, deletable)

#### Scenario: Notice on uploader hover
- **WHEN** the user hovers the file uploader help icon
- **THEN** the tooltip MUST contain the same privacy facts

### Requirement: ToS Versioned Acceptance
The system MUST require first-time users to accept a versioned Terms of Service before they can start an interview.

#### Scenario: First-time gate
- **WHEN** a user opens the app for the first time (no consent record for current `TOS_VERSION`)
- **THEN** the main area MUST show a ToS modal with the full ToS text and an accept checkbox
- **AND** the "开始面试" button MUST remain disabled until the user ticks the checkbox and clicks "确认接受"

#### Scenario: Returning user skips modal
- **WHEN** a user opens the app and a consent record exists for the current `TOS_VERSION`
- **THEN** the ToS modal MUST NOT render
- **AND** the "开始面试" button MUST be enabled (subject to other guards)

#### Scenario: ToS version bump re-triggers modal
- **WHEN** the `TOS_VERSION` constant is incremented
- **AND** an existing user loads the app
- **THEN** the ToS modal MUST render again
- **AND** on accept, a new consent record for the new version MUST be persisted

### Requirement: Single Session Deletion
The system MUST allow users to delete any single historical interview session from the sidebar, with a confirmation step.

#### Scenario: Delete button visible per session
- **WHEN** the sidebar history list contains at least one session
- **THEN** each session entry MUST show a delete control (icon or button)

#### Scenario: Confirmation required
- **WHEN** the user clicks the delete control for a session
- **THEN** the system MUST show a confirmation dialog naming the session date and turn count
- **AND** the session MUST NOT be removed until the user confirms

#### Scenario: Successful deletion
- **WHEN** the user confirms the deletion
- **THEN** the session and its turns and feedback MUST be removed from storage
- **AND** the sidebar history MUST refresh (rerun) without the deleted entry
- **AND** if the user was viewing the deleted session, the view MUST return to the empty state

### Requirement: Bulk Clear All History
The system MUST allow the user to delete all historical sessions for the current candidate with a double-confirmation flow.

#### Scenario: Bulk delete button visible
- **WHEN** the sidebar history contains at least one session
- **THEN** a "清空我的全部历史" button MUST be visible

#### Scenario: Typed confirmation required
- **WHEN** the user clicks the bulk delete button
- **THEN** the system MUST require the user to type the literal string "确认删除" to enable the confirm action

#### Scenario: Successful bulk clear
- **WHEN** the user types the confirmation string and confirms
- **THEN** all sessions for the current candidate MUST be removed
- **AND** the sidebar MUST show the empty state

### Requirement: Automatic Retention Cleanup
The system MUST automatically delete sessions older than the configured retention period on application load.

#### Scenario: Default 30-day retention
- **WHEN** `STORAGE_RETENTION_DAYS` is unset
- **THEN** the retention period MUST default to 30 days

#### Scenario: Configurable retention
- **WHEN** `STORAGE_RETENTION_DAYS` is set to N
- **THEN** sessions with `ended_at` older than N days MUST be removed on the next app load

#### Scenario: Cleanup is lazy
- **WHEN** no app load occurs, sessions MUST NOT be deleted by a background process
- **AND** the system MUST NOT introduce a new background scheduler dependency

### Requirement: Consent Log Persistence
The system MUST persist ToS acceptance records in a dedicated table, indexed by candidate ID and ToS version, so that acceptance is auditable per user.

#### Scenario: New table created idempotently
- **WHEN** `init_db` runs
- **THEN** a `consent_log` table MUST be created if it does not exist
- **AND** the table MUST have columns: candidate_id (TEXT), tos_version (TEXT), accepted_at (TEXT)
- **AND** a UNIQUE(candidate_id, tos_version) constraint MUST exist

#### Scenario: Resume text never stored in consent log
- **WHEN** a ToS acceptance is recorded
- **THEN** the consent_log row MUST NOT contain resume text or PII
- **AND** only the MD5 candidate_id (same as interview_sessions) MUST be stored
