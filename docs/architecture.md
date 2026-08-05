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

## F005/F006 implementation note (interim deterministic reference pipeline)

`agents/reference_pipeline.py` implements `extract_and_validate(segments,
meeting_id) -> list[ValidatedItem]`, combining F005 (extraction) and F006
(commitment validation) behind one interface. It is currently a
pattern/keyword-based deterministic implementation, not an LLM call: it has
no network dependency, no API key requirement, and is fully reproducible in
CI. This was a deliberate scoping choice to unblock F007-F010 (owner
resolution, date resolution, the safety gate) without first standing up and
evaluating a Groq-backed extraction prompt against `F016`'s eval harness.

An LLM-backed implementation is still the target (per `docs/product.md`)
and can replace this module's body without changing any downstream caller,
since F007-F010 only consume `ValidatedItem`/`ResolvedItem` objects, never
this module's internals. When that swap happens, `F016`'s evaluation
harness must show the LLM implementation is at least as accurate as this
reference implementation on the fixture set before it replaces it as the
default.

Known scope limits of the current reference implementation (see
`progress.md` for the session that introduced it): it recognizes a fixed,
small set of English request/affirm/negative/cancel/correction phrases plus
a documented, controlled Telugu lexicon (`chesthava`, `chesthanu`,
`పంపిస్తాను`, postpositions `ki`/`varaku`) for the one code-switched pair
the product brief asks for. It is not general sentiment or intent
classification and will misclassify phrasing outside its fixture set.

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
