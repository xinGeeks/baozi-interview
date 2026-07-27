# user-data-privacy Specification

## Purpose
TBD - created by archiving change alpha-kickoff. Update Purpose after archive.
## Requirements
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

