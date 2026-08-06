# Nexvi.Meets — Architecture

## Shape

Layered (ports-and-adapters) with an explicit agent/tool layer on top.
Dependencies point **inward only**: `api → agents → tools → services →
domain`, with `adapters` plugged in from the outside.

```
backend/app/
  core/                     configuration
    config.py               one Settings; require_* helpers fail loudly

  domain/                   PURE. no network, no database, no LLM.
    models.py               every schema in docs/data-contracts.md
    safety/gate.py          the six deterministic rules

  tools/                    the agent-facing capability layer
    base.py                 ToolSpec, Tool protocol, FunctionTool
    registry.py             ToolRegistry + Authorization  <-- the chokepoint
    catalog.py              17 tools; exactly 4 are side-effecting

  agents/                   orchestration
    base.py                 Agent protocol, PipelineState, step execution
    pipeline_agents.py      7 agents, one per pipeline stage
    orchestrator.py         in-house AgentGraph (default runtime)
    langgraph_runtime.py    LangGraph runtime over the same agents

  services/                 business logic the tools wrap
    ingestion/              parser.py (txt/vtt/srt), normalization.py
    extraction/             base.py (protocol + citation grader),
                            groq.py (primary), reference.py (fallback)
    resolvers/              owner.py, date.py, combine.py
    normalization.py        Sarvam code-switch translation (additive)
    confidence.py           composite scoring
    meeting_record.py       structured record synthesis
    idempotency.py          dedupe key
    audit.py                append-only audit writer
    payload.py              the exact IssuePayload
    approval.py             THE side-effect chokepoint
    pipeline.py             assembly: context, runtime, persistence
    live.py                 rolling-window live session
    evaluation.py           scorer against labelled data

  adapters/                 the I/O boundary
    repositories/           base | mongo (runtime) | memory (tests)
    trackers/               base | github (runtime) | memory (tests)
    calendar/               base | google (runtime) | memory (tests)
    memory/                 base | chroma (runtime) | memory (tests)

  api/
    deps.py                 dependency wiring (overridable in tests only)
    schemas.py              request/response DTOs, separate from domain
    routes/                 health | meetings | review | system | live
```

`frontend/src/` is the React UI. `tests/fixtures/` at the repo root is the
transcript corpus plus `labels.json`, the evaluation dataset.

## Why there is an agent layer at all

The brief's FAQ: *"What counts as agentic here? The system decides what
actions are needed and executes them through tools."*

So the pipeline is not a function that calls other functions. It is seven
named agents, each declaring the tools it may use, executed by a graph
that records every step, and every capability is a registered `Tool` with
metadata. `GET /system/agents` and `GET /system/tools` expose that at
runtime, and `GET /system/meetings/{id}/agent-run` returns the actual
recorded run — so "agentic" is inspectable rather than asserted.

```
IngestionAgent      parse_transcript
NormalizationAgent  normalize_segments, translate_segments
ExtractionAgent     extract_candidates
ValidationAgent     grade_evidence
ResolutionAgent     resolve_items
GateAgent           safety_gate
RecordAgent         synthesize_record, recall_memory
--------------- human review interrupt ---------------
(approval service)  github_issue, calendar_invite, memory_index, notification
```

The graph **always stops** at the interrupt. Resuming is a separate,
human-initiated call. An interrupt the system could resume by itself
would not be a safety property.

## The non-negotiable boundary

Per `AGENTS.md`: the LLM may interpret the meeting; deterministic code
decides whether an external action is allowed. Four structural properties
enforce that, each covered by a test rather than a comment:

**1. The gate cannot read prose.** `check_gate(item: ResolvedItem,
confidence_threshold: float)` has no parameter through which transcript
text or a model response could reach it.

**2. Side effects require proof of authorisation.**
`ToolRegistry.invoke` refuses to call a side-effecting tool without an
`Authorization` — a passing `GateDecision` plus an approving
`ReviewDecision` *for the same candidate*. Not a boolean flag: the two
decision objects, so the audit log can always say why an action was
permitted. An agent cannot reach GitHub by forgetting the gate, because
forgetting the gate means having no `Authorization` to pass.

**3. An extractor cannot grade its own citations.**
`drop_unsupported_evidence` runs *outside* the extractor and deletes any
evidence quote that is not a literal substring of the segment it names.

**4. Translation cannot weaken evidence.** Sarvam normalization is
additive: `segment.text` stays verbatim and is what quotes are validated
against; `segment.normalized_text` is extraction input only. Translating
in place would have silently destroyed every citation on a code-switched
transcript.

## Two agent runtimes

| | in-house (`orchestrator.py`) | LangGraph (`langgraph_runtime.py`) |
|---|---|---|
| Default | yes | opt in via `AGENT_RUNTIME=langgraph` |
| Dependency | none | `langgraph` |
| Routing | named condition functions | linear edges |
| Fallback | — | falls back to in-house if unavailable |

Both drive the **same** `Agent` objects, so behaviour cannot diverge —
only the scheduler differs. The archived code carried a warning in its own
docstring that LangGraph's API shifts between minor versions; rather than
choose between recognisability and reliability, Nexvi.Meets has both and
degrades the scheduler, never the pipeline.

## Four gated side effects

`github_issue`, `calendar_invite`, `memory_index`, `notification`. Each is
independently gated, independently idempotent, and independently audited.
One failing does not roll back the others — they are separate external
systems, and a failed calendar invite must not delete a GitHub issue that
succeeded. A reviewer opts into each per approval; the default is GitHub
alone, so approving never fans out further than the person expected.

Duplicate suppression is enforced by **unique database indexes** on
`nm_issues.dedupe_key` and `nm_calendar.dedupe_key`, not by application
logic alone, so it holds under concurrent approvals.

## Failure posture

Everything fails *closed*. Unresolvable owner → `unresolved`, never a
guess. Unparseable date → `null`, never today. Unknown classification from
the model → coerced to `suggestion`, which can never pass the gate.
Missing credentials → a loud error, never a silent in-memory substitute.
A tracker error → HTTP 502 plus an audit event, never a success response.
A Sarvam outage → original text, pipeline unaffected. A memory-store
outage → recall skipped with a warning, upload unaffected.

The in-memory repository, tracker, calendar and memory store exist only
for tests, injected through `app.dependency_overrides`. `api/deps.py`
constructs only real implementations, so no configuration mistake can make
a live demo record actions to nowhere and report success.

## Changing this document

Any change to the layering, the boundary, the tool catalogue, or the
extraction contract must update this file in the same commit
(`AGENTS.md` scope rules).
