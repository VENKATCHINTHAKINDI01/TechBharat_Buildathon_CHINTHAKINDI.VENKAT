# Legacy — Nexvi.Meets (archived, not deleted)

This directory holds the original **Nexvi.Meets** implementation that
existed in this repository before it became CommitGuard. It is kept for
reference and recoverability. **Nothing here is imported, executed, or
tested by the running application.**

`scripts/verify.sh` and `pytest` both exclude this directory. A test in
`backend/tests/integration/test_scaffold.py`
(`test_app_does_not_import_legacy_nexvi_modules`) fails if any of it is
ever pulled back into the live import graph by accident.

## Why it was archived rather than kept live

The legacy pipeline could reach a real external side effect (a Google
Calendar invite) without passing through any deterministic safety gate.
The TechBharat brief's hard metric is *exactly zero* unapproved actions,
and `AGENTS.md`'s non-negotiable principle is that deterministic code —
not the LLM — decides whether an external action is allowed. Rather than
retrofit a gate onto two divergent pipelines, the useful parts were
absorbed into CommitGuard and the rest parked here.

## What was absorbed into CommitGuard

| Legacy file | Where it lives now | Note |
|---|---|---|
| `backend/tools/dedupe_hash_tool.py` | `app/services/idempotency.py` | same SHA-256 approach, now keyed on the resolved owner id rather than the raw spoken name |
| `backend/db/mongo.py` | `app/adapters/repositories/mongo.py` | motor client + index creation, now behind a repository protocol |
| `backend/tools/audit_log_tool.py` | `app/services/audit.py` + repository | audit writing is now mandatory on every stage, not optional |
| `backend/tools/groq_extract_tool.py` | `app/services/extraction/groq.py` | prompt reworked to demand verbatim evidence quotes and segment ids |
| `backend/review/routes.py` | `app/api/routes/review.py` | endpoint shapes kept; approval now additionally requires a passing gate decision server-side |
| `backend/models/*.py` | `app/domain/models.py` | consolidated, with evidence/classification/gate fields the legacy models lacked |
| `backend/frontend/*` | `frontend/src/` | rebuilt against the CommitGuard API with an evidence drawer |

## What was intentionally left behind

- **Google Calendar integration** (`integrations/google_calendar_client.py`,
  `tools/calendar_tool.py`) — the brief asks for *one* deep integration;
  CommitGuard's is GitHub Issues. Calendar is a P2 item in `AGENTS.md`.
- **Live/websocket mode** (`websocket/`, `ingestion/live_receiver.py`,
  `tools/rolling_window_tool.py`) — P2, and several of these files were
  empty stubs.
- **Sarvam normalization** (`tools/sarvam_normalize_tool.py`) — CommitGuard
  handles the English+Telugu code-switched pair directly in the extractor
  and date resolver, without a translation round-trip that would destroy
  the verbatim evidence quotes the gate depends on.
- **Reminders / notifications** (`tools/reminder_*.py`,
  `agents/notification_agent.py`) — P2.
- **ChromaDB indexing** (`db/chroma.py`, `tools/chroma_index_tool.py`) —
  belongs to cross-meeting memory, which is P2.
- **`backend/tests/`** — four empty placeholder files, superseded by the
  real suite under `backend/tests/`.

## Restoring something from here

Copy the file into the appropriate layer under `backend/app/`, give it a
feature id in `feature_list.json`, write its acceptance criteria in
`docs/acceptance-tests.md`, and write tests before wiring it in — the
same process as any new feature. Do not import directly from this
directory.
