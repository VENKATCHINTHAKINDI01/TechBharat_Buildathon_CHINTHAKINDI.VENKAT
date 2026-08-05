# CommitGuard — Architecture

## Placement in the existing repository

CommitGuard is built **inside** the existing Nexvi.Meets `backend/` and
`frontend/` trees, under its own namespace, so it can reuse shared
infrastructure without coupling to or silently modifying the existing
meeting-summarization product.

```
backend/
  app/
    commitguard/
      __init__.py
      routes.py            # FastAPI router, mounted at /commitguard
      models/               # Pydantic schemas (F004)
      ingestion/            # txt/vtt/srt parsing + normalization (F002, F003)
      agents/                # extraction + validation LLM passes (F005, F006)
      resolvers/             # owner resolution, date resolution (F007, F008)
      safety/                 # deterministic safety gate (F010)
      tools/                  # github_issues_tool.py etc. (F014)
      audit/                  # event store (F011)
      eval/                    # evaluation dataset + scorer (F016)
    main.py                  # existing app; will mount commitguard router
frontend/
  src/
    commitguard/
      ReviewScreen.jsx        # human review UI (F013)
      EvidenceDrawer.jsx
      api.js
```

Shared, reused as-is: `app/config.py` (Settings), `app/db/mongo.py` (Mongo
connection), the base FastAPI app in `app/main.py` (CommitGuard's router is
mounted onto it, not a separate app). CommitGuard uses its own Mongo
collections (prefixed `commitguard_*`) and its own Pydantic schemas — it
must not reuse or mutate Nexvi.Meets' `Meeting` / `ActionItem` models.

## Pipeline (high level)

```
transcript file
   -> ingestion (F002)              deterministic parsing
   -> normalization (F003)          deterministic, speaker segments
   -> extraction (F005)             LLM: propose candidates + evidence quotes
   -> commitment validation (F006)  LLM: classify + detect contradictions
   -> owner resolution (F007)       deterministic, against participant directory
   -> date resolution (F008)        deterministic, against meeting date
   -> safety gate (F010)            deterministic, computes eligibility
   -> persistence + audit (F011)    every stage writes an audit event
   -> human review API (F012)       reviewer sees all candidates + evidence
   -> [human approval]              required before any external call
   -> GitHub Issues tool (F014)     only path that calls GitHub; gated by F010 + approval
   -> idempotency check (F015)      dedupe before create
```

## The non-negotiable boundary

Per `AGENTS.md`: the LLM (extraction, validation) may produce interpretation
and classification, but a separate, deterministic module (`safety/gate.py`)
is the only code allowed to decide whether a candidate is eligible for
GitHub creation, and the GitHub tool (`tools/github_issues_tool.py`) is the
only code allowed to call the GitHub API. The LLM never calls tools/GitHub
directly and never bypasses the gate. This boundary is enforced by module
structure (LLM-calling code and side-effecting code do not import each
other) and will be covered by the F010/F014 tests.

## Data stores

- MongoDB (existing `nexvi_meets` database, `commitguard_*` collections):
  candidates, resolved items, audit events, review decisions.
- No Chroma dependency for CommitGuard P0/P1 (cross-meeting memory is P2 and
  out of scope for now).

## Changes to this document

Any change to this pipeline, the module boundary, or the repo placement
decision must update this file in the same commit, per `AGENTS.md` scope
rules.
