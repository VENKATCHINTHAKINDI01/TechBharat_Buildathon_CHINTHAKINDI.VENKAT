# AGENTS.md — Nexvi.Meets Buildathon Harness

## Mission

Build **Nexvi.Meets**, an evidence-backed meeting commitment agent for the TechBharat Buildathon.

The product must:

1. ingest a meeting transcript,
2. extract decisions, risks, blockers, open questions, and action-item candidates,
3. distinguish real commitments from suggestions, disputes, rejections, and cancellations,
4. resolve owners and relative dates,
5. require human approval before any external side effect,
6. create approved tasks in GitHub Issues,
7. suppress duplicates,
8. record a complete audit trail.

The differentiator is not summarization. The differentiator is **commitment integrity**.

## Non-negotiable product principle

> The LLM may interpret the meeting. Deterministic code decides whether an external action is allowed.

No task may be created unless:

- the item is classified as `confirmed`,
- an owner resolves to one real participant,
- supporting transcript evidence exists,
- no unresolved contradiction is present,
- confidence is at or above the configured threshold,
- a human explicitly approves the exact payload.

## Repository reading order

At the start of every session, read:

1. `AGENTS.md`
2. `docs/product.md`
3. `docs/architecture.md`
4. `docs/data-contracts.md`
5. `feature_list.json`
6. `progress.md`
7. `git log --oneline -10`

Then run:

```bash
bash init.sh
```

Do not implement anything before initialization succeeds.

## Session lifecycle

### Start

1. Read the required files.
2. Run `bash init.sh`.
3. Inspect `feature_list.json`.
4. Select exactly one feature with status `todo` or `in_progress`.
5. Mark only that feature as `in_progress`.

### Execute

1. Write or update tests first.
2. Implement the smallest change that satisfies the feature.
3. Run targeted tests.
4. Run `bash scripts/verify.sh`.
5. Fix all failures.
6. Record verification evidence.

### Finish

1. Update `feature_list.json`.
2. Update `progress.md`.
3. Record known limitations honestly.
4. Leave the repository in a runnable state.
5. Commit only after verification passes.

## Scope rules

- Work on one feature at a time.
- Do not add features not listed in `feature_list.json`.
- Do not rewrite architecture without updating `docs/architecture.md`.
- Do not modify shared schemas silently.
- Do not replace deterministic safety checks with LLM judgement.
- Do not let the LLM call GitHub directly.
- Do not add Slack, Jira, Calendar, email, live audio, or real-time mode unless all P0 and P1 items pass first.
- Do not claim completion based on visual inspection.

## Build priorities

### P0 — must pass

- transcript ingestion
- structured extraction
- commitment classification
- owner resolution
- date resolution
- evidence linking
- deterministic safety gate
- human review
- GitHub Issues integration
- idempotency
- audit log
- end-to-end test
- evaluation report

### P1 — strong differentiators

- disagreement detection
- owner reassignment tracking
- deadline change tracking
- cancellation detection
- code-switched English + Telugu or English + Hindi fixture

### P2 — only after everything above is stable

- audio transcription
- cross-meeting memory
- reminders
- live meeting mode
- analytics

## Definition of done

A feature is done only when:

- implementation exists,
- tests exist,
- tests pass,
- lint/type checks pass,
- the feature works in the end-to-end flow,
- evidence is recorded in `progress.md`.

## Forbidden completion language

Do not write:

- "should work"
- "looks correct"
- "probably fixed"
- "done" without evidence

Instead write:

- tests run,
- command outputs,
- fixtures passed,
- remaining failures,
- exact files changed.

## Required output after each task

Return:

```text
Feature:
Files changed:
Tests added:
Commands run:
Verification result:
Known limitations:
Next recommended feature:
```

## Relationship to the existing Nexvi.Meets codebase

Nexvi.Meets is built **inside** the existing `backend/` (FastAPI/LangGraph) and
`frontend/` (React/Vite) trees rather than as a parallel project. It lives under
its own namespace so it can be developed and tested without disturbing the
existing Nexvi.Meets meeting-summarization code:

- `backend/app/` — the application: `core`, `domain`, `tools`, `agents`,
  `services`, `adapters`, `api`. See `docs/architecture.md`.
- `frontend/src/` — the review UI (review screen, evidence drawer, agent
  trace, live panel).

Shared infrastructure (Mongo connection, Chroma client, base FastAPI app,
Settings) may be reused, but Nexvi.Meets's own schemas, safety gate, and
GitHub tool must not be merged into or silently altered by Nexvi.Meets code,
and vice versa.
