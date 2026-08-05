# CommitGuard — Architecture

## Shape

Layered (ports-and-adapters). Dependencies point **inward only**:
`api → services → domain`, with `adapters` plugged in from the outside.

```
backend/app/
  core/                     configuration
    config.py               one Settings; require_* helpers fail loudly

  domain/                   PURE. no network, no database, no LLM.
    models.py               every schema in docs/data-contracts.md
    safety/gate.py          the six deterministic rules

  services/                 orchestration and business logic
    ingestion/
      parser.py             txt / vtt / srt  (F002)
      normalization.py      -> TranscriptSegment (F003)
    extraction/
      base.py               Extractor protocol + drop_unsupported_evidence
      groq.py               LLM extractor (primary)      (F005/F006)
      reference.py          deterministic extractor (fallback + test baseline)
    resolvers/
      owner.py              exact/fuzzy/unresolved       (F007)
      date.py               relative -> absolute          (F008)
      combine.py            ValidatedItem -> ResolvedItem
    meeting_record.py       structured record synthesis   (F011b)
    idempotency.py          dedupe key                    (F015)
    audit.py                append-only audit writer      (F011)
    payload.py              the exact IssuePayload
    approval.py             THE chokepoint for side effects
    pipeline.py             end-to-end orchestration
    evaluation.py           scorer against labelled data  (F016)

  adapters/                 the I/O boundary
    repositories/           base.py | mongo.py (runtime) | memory.py (tests)
    trackers/               base.py | github.py (runtime) | memory.py (tests)

  api/
    deps.py                 dependency wiring (overridable in tests only)
    schemas.py              request/response DTOs, separate from domain models
    routes/                 health.py | meetings.py | review.py
```

`frontend/src/` is the React review UI (`api/client.js`, `components/`).
`legacy/` holds the archived pre-CommitGuard tree — see `legacy/README.md`.

## The non-negotiable boundary

Per `AGENTS.md`: the LLM may interpret the meeting; deterministic code
decides whether an external action is allowed. Three structural properties
enforce that, each covered by a test rather than a comment:

**1. The gate cannot read prose.** `check_gate(item: ResolvedItem,
confidence_threshold: float) -> GateDecision` has no parameter through
which transcript text or a model response could reach it. Asserted by
`test_gate_signature_cannot_receive_raw_transcript_text`.

**2. The extractor cannot cause a side effect.** An `Extractor` returns
`list[ValidatedItem]` and nothing else. `services/extraction/` does not
import `adapters/trackers/`, and has no repository handle. The only caller
of a tracker is `services/approval.py`.

**3. An extractor cannot grade its own citations.**
`drop_unsupported_evidence` runs *outside* the extractor and deletes any
evidence quote that is not a literal substring of the segment it names. An
`action_item` left with no surviving evidence is dropped entirely.

Everything an approval must satisfy converges in one function,
`approval.approve_and_create_issue`: re-run the gate server-side (never
trust the client's last render), require an explicit `ReviewDecision`,
check the dedupe key *before* the network call, and write an audit event on
every branch — including refusals and failures.

## Extraction: two implementations, one protocol

| | `groq.py` | `reference.py` |
|---|---|---|
| Role | primary when `GROQ_API_KEY` is set | fallback; the only extractor tests use |
| Determinism | no | yes |
| Network | yes | no |
| Failure | raises `ExtractionError` → falls back | n/a |

Both return `list[ValidatedItem]`, so resolution, the gate, review and the
tracker are byte-identical regardless of which produced the candidates.
A provider outage degrades output *quality*; it never loses the meeting and
never changes what is allowed to happen.

The reference implementation is pattern-based over a small fixture set, not
general NLU. It recognizes a fixed set of English request/affirm/decline/
cancel phrases plus a documented Telugu lexicon (`chesthava`, `chesthanu`,
`పంపిస్తాను`, postpositions `ki` / `varaku`) for the one code-switched pair
the brief asks for. It will misclassify phrasing outside that set — which
is exactly why Groq is primary.

## Failure posture

Everything fails *closed*. Unresolvable owner → `unresolved`, never a
guess. Unparseable date → `null`, never today's date. Unknown
classification from the model → coerced to `suggestion`, which can never
pass the gate. Missing credentials → a loud error, never a silent
in-memory substitute. A tracker error → HTTP 502 plus an audit event,
never a success response.

The in-memory repository and tracker exist only for tests, injected through
`app.dependency_overrides`. `api/deps.py` constructs only the real
implementations, so no configuration mistake can make a live demo record
issues to nowhere and report success.

## Changing this document

Any change to the layering, the boundary, or the extraction contract must
update this file in the same commit (`AGENTS.md` scope rules).
