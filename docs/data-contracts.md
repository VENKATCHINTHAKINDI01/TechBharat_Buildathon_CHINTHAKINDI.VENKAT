# CommitGuard — Data Contracts

Schemas below are the target shape for `backend/app/commitguard/models/`
(Pydantic). They are defined here first (per `AGENTS.md`: "Do not modify
shared schemas silently") and will be implemented under feature `F004`.
This document is the source of truth; implementation must match it, and any
change to a shape here must be a deliberate edit to this file.

## TranscriptSegment (produced by F003)

| field | type | notes |
|---|---|---|
| `segment_id` | str | stable id within the transcript |
| `speaker` | str | raw speaker label as it appears in the source file |
| `start_ms` | int \| null | if timing is available (vtt/srt) |
| `end_ms` | int \| null | if timing is available (vtt/srt) |
| `text` | str | normalized segment text |

## CandidateItem (produced by F005)

| field | type | notes |
|---|---|---|
| `candidate_id` | str | |
| `meeting_id` | str | |
| `kind` | enum: `decision`, `risk`, `blocker`, `open_question`, `action_item` | |
| `raw_text` | str | LLM-proposed description |
| `evidence_quotes` | list[EvidenceQuote] | must be non-empty for `action_item` |
| `raw_owner_mention` | str \| null | as spoken, before resolution |
| `raw_date_mention` | str \| null | as spoken, before resolution |
| `confidence` | float [0,1] | model-reported confidence |

### EvidenceQuote

| field | type | notes |
|---|---|---|
| `segment_id` | str | references `TranscriptSegment.segment_id` |
| `quote` | str | must be a verbatim substring of the referenced segment |

## ValidatedItem (produced by F006, extends CandidateItem)

| field | type | notes |
|---|---|---|
| `classification` | enum: `confirmed`, `suggestion`, `disputed`, `rejected`, `cancelled` | |
| `contradiction_of` | str \| null | `candidate_id` of an earlier item this supersedes/cancels, if any |
| `contradiction_note` | str \| null | human-readable reason |

## ResolvedItem (produced by F007 + F008, extends ValidatedItem)

| field | type | notes |
|---|---|---|
| `owner_participant_id` | str \| null | null if unresolved |
| `owner_resolution_method` | enum: `exact_match`, `fuzzy_match`, `unresolved` | |
| `due_date` | date (ISO 8601) \| null | null if unresolved |
| `date_resolution_method` | enum: `absolute`, `relative`, `unresolved` | |

## GateDecision (produced by F010)

| field | type | notes |
|---|---|---|
| `candidate_id` | str | |
| `eligible` | bool | |
| `reasons` | list[str] | every failing check, even if `eligible=true` has none |
| `checked_at` | datetime | |

Eligibility requires ALL of: `classification == confirmed`,
`owner_participant_id is not null`, `evidence_quotes` non-empty,
`contradiction_of is null` (or resolved), `confidence >= threshold`
(threshold defined in Settings, not hardcoded in the gate function).

## ReviewDecision (produced by F012)

| field | type | notes |
|---|---|---|
| `candidate_id` | str | |
| `reviewer` | str | |
| `decision` | enum: `approved`, `rejected`, `edited_and_approved` | |
| `final_payload` | dict \| null | exact GitHub issue payload, required if approved |
| `decided_at` | datetime | |

## AuditEvent (produced by every stage, F011)

| field | type | notes |
|---|---|---|
| `event_id` | str | |
| `meeting_id` | str | |
| `candidate_id` | str \| null | |
| `stage` | enum: `ingestion`, `extraction`, `validation`, `resolution`, `gate`, `review`, `github_create`, `dedupe` | |
| `payload` | dict | stage-specific detail, must be JSON-serializable |
| `created_at` | datetime | |

## GitHubIssueRecord (produced by F014, keyed for F015 idempotency)

| field | type | notes |
|---|---|---|
| `dedupe_key` | str | deterministic hash of `(meeting_id, owner_participant_id, normalized_text)` |
| `candidate_id` | str | |
| `github_issue_number` | int | |
| `github_issue_url` | str | |
| `created_at` | datetime | |

## Change control

Any addition or modification to a field above must be reflected here in the
same commit as the code change (`AGENTS.md`: "Do not modify shared schemas
silently").
