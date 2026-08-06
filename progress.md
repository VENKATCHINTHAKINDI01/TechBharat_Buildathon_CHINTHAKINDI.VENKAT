# Progress Log

## Current state

**Complete, runnable, agentic end-to-end product.** 28 of 29 features are
`done`; only `F019` (evaluation report and demo freeze) remains.

A transcript — uploaded or streamed live — is parsed, optionally
translated for comprehension, extracted and classified by an LLM,
citation-checked by deterministic code, resolved for owner and date,
scored, gated by six deterministic rules, synthesized into a structured
meeting record, reviewed by a human, and then turned into a GitHub issue,
a Calendar invite, a cross-meeting memory entry and a notification record
— each independently gated, idempotent and audited.

The original Nexvi.Meets prototype tree has been fully absorbed and removed;
everything worth keeping now lives in the live codebase with tests.

Verification: `bash scripts/verify.sh` exits 0; **399 tests pass** with no
network access and no credentials; the frontend builds clean.

## Active feature

None. Next pick is `F019`.

## Completed features

F001 scaffold · F002 ingestion · F003 normalization · F004 schemas ·
F004b priority · F005 extraction · F006 validation · F007 owner
resolution · F008 date resolution · F009 disagreement/cancellation ·
F010 safety gate · F011 persistence + audit · F011b meeting record ·
F012 review API · F013 review frontend · F014 GitHub Issues ·
F015 idempotency · F016 evaluation harness · F017 code-switched fixture ·
F018 end-to-end test · **F020 tool registry** · **F021 multi-agent
orchestration** · **F022 composite confidence** · **F023 code-switch
normalization** · **F024 Calendar** · **F025 cross-meeting memory** ·
**F026 notifications** · **F027 live meeting mode**.

## Verification evidence

```
bash init.sh                        -> exit 0, "Initialization complete."
bash scripts/verify.sh              -> exit 0, "all checks passed"
cd backend && pytest -q tests       -> 399 passed
cd frontend && npm run build        -> built, no errors
```

| Suite | N | Covers |
|---|---|---|
| `unit/test_gate.py` | 170 | F010, exhaustive 160-case truth table |
| `unit/test_ingestion.py` | 19 | F002/F003, all fixtures + vtt/srt/malformed |
| `integration/test_side_effects.py` | 17 | F024–F027, multi-effect approval, live ws |
| `integration/test_review_flow.py` | 17 | F012/F014/F015/F018 |
| `unit/test_normalization_and_confidence.py` | 13 | F022/F023 |
| `unit/test_agents.py` | 13 | F021 graph, routing, tracing, interrupt |
| `unit/test_tool_registry.py` | 11 | F020 authorisation enforcement |
| `unit/test_schemas.py` | 11 | F004 round-trip + validation |
| `unit/test_groq_extractor.py` | 11 | LLM parsing, stubbed client |
| `unit/test_date_resolution.py` | 11 | F008 incl. Telugu postpositions |
| `unit/test_extraction_validation.py` | 10 | F005/F006/F009 |
| `unit/test_owner_resolution.py` | 8 | F007 fail-closed |
| `unit/test_meeting_record.py` | 8 | F011b partition |
| `unit/test_live_mode.py` | 8 | F027 rolling window + dedupe |
| `unit/test_idempotency.py` | 6 | F015 |
| `unit/test_evidence_filter.py` | 6 | citation grading |
| `integration/test_scaffold.py` | 5 | F001 + boundary guards |
| `unit/test_evaluation.py` | 5 | F016 scorer + measured baseline |
| `unit/test_priority_field.py` | 4 | F004b |

`scripts/verify.sh` additionally proves *structurally* that:

- extraction and the agents cannot import a side-effecting adapter,
- only `approval.py` invokes a side-effecting tool,
- `check_gate`'s signature has not drifted to accept free text,
- `backend/.env` is untracked,
- every labelled fixture exists on disk,
- no feature is `done` while a dependency is not.

Evaluation (F016), deterministic extractor: recall 87.5%, precision 100%,
owner 100%, date 100%, gate-vs-label 100% — all four brief targets met.
The single recall miss (`disagreement.txt` → "roll back the deploy") is a
`decision`, not an `action_item`; left visible rather than relabelled to
manufacture a perfect score.

## Known limitations — read before demoing

- **No live run against real Mongo, Groq, GitHub or Calendar has been
  performed in this environment.** All 399 tests use in-memory adapters,
  a stubbed Groq client, and a scripted transcriber. The real adapters are written and typed but
  their live behaviour is unverified. This is the highest-risk gap.
- **The evaluation numbers are on fixtures we wrote *and* labelled.** Not
  a gold transcript. The deterministic extractor is pattern-based; on
  unseen phrasing it will score far lower. The Groq path is unmeasured.
- The deterministic extractor recognises a fixed English phrase set plus a
  documented Telugu lexicon (`chesthava`, `chesthanu`, `పంపిస్తాను`, `ki`,
  `varaku`). One rewrite (`_CHECKLIST_CHESI_RE`) is a hand-written special
  case for the brief's flagship sentence — flagged in the code, not hidden.
- Reminder times are computed **intent**; no background scheduler fires
  them. The Calendar invite is the real notification. Carried over
  honestly from the archived implementation.
- The LangGraph runtime is implemented and falls back cleanly, but has not
  been exercised against an installed LangGraph in this environment — the
  fallback path is what the tests cover.
- Cross-meeting carry-forward surfaces matches but does not yet mark items
  completed or flag twice-slipped commitments (brief stretch goal, partial).
- **Live audio is untested against real speech.** The transcription
  adapters, the two-track capture, and the diarization mapping are all
  covered by tests with scripted/mocked audio, but no real microphone or
  meeting tab has run through them here. Chunk size, echo between the mic
  and tab tracks, and Whisper's behaviour on six-second slices of natural
  conversation are all unmeasured.
- Sarvam's diarization response shape is handled defensively but was
  never observed live; a schema mismatch degrades to "no refinement".
- Mic and tab tracks may both pick up your own voice if you use speakers
  rather than headphones, producing duplicate segments. Use headphones.
- Latency against "under 3 minutes for a 45-minute meeting" is unmeasured.
- No lint/type-check step; the repo has no ruff/mypy config.
- The frontend has no automated tests beyond the build.

### 2026-08-05 — Session 6 (live mode re-engineered around real audio)

Live mode previously accepted typed lines. It now captures actual audio.

- **F028 capture.** Browser records the mic and the shared meeting tab as
  two tracks. The non-obvious part: a `MediaRecorder`'s 2nd+ WebM blobs
  carry no container header, so slicing one recording yields chunks
  nothing can decode. The frontend cycles a fresh recorder per interval
  instead, making every chunk a complete file — which is also what lets a
  plain file-upload STT endpoint drive a live experience.
- **F029 transcription.** `Transcriber` protocol with Groq Whisper primary
  (~216x realtime, accepts browser WebM directly), Sarvam Saarika
  re-transcribing Indic speech, and a `NullTranscriber` that refuses
  rather than returning empty text that would look like a silent meeting.
- **F030 attribution.** Track-based live (mic = certain, tab = unknown),
  one-click tagging that propagates across a speaker cluster, and an
  end-of-meeting Sarvam diarization pass mapped back by time overlap.
  A segment with no overlapping turn stays unassigned; diarization never
  overwrites a human confirmation.
- **Consent gate.** The session refuses audio until consent is
  acknowledged, and the acknowledgement is audited. Not requested, but
  recording people without their knowledge is unlawful in many places and
  the brief says so explicitly.

Test count 353 -> 399. One implementation trap worth recording: the first
full-suite run after wiring the new dependencies **hung**, because the
live websocket tests were constructing the real Groq transcriber and
calling the network with the developer's actual key. Fixed by overriding
`get_transcriber`/`get_diarizer` in the integration conftest — the same
mistake would have hit anyone adding a new adapter dependency.

## Session log

### 2026-08-05 — Sessions 1–3

Built the harness and F001–F010 in dependency order, tests first. After the
official brief PDF arrived, added F004b (`priority`) and F011b
(`MeetingRecord`) to close two compliance gaps, and corrected
`docs/acceptance-tests.md`, which had described F009 behaviour the
implementation never had.

### 2026-08-05 — Session 4

Restructured into ports-and-adapters, archived the legacy tree, and built
F011–F018: Mongo persistence with unique-index idempotency, the review
API, the GitHub tracker, the Groq extractor with deterministic fallback,
the React review UI, and the evaluation harness.

### 2026-08-05 — Session 5 (agents, tools, and full legacy reintegration)

Per the user's decision, the archived tree was **unarchived, absorbed, and
deleted** — everything of value now lives in the live codebase with tests.

- **F020 tool registry.** Every capability is a declared `Tool` with
  metadata. `ToolRegistry.invoke` refuses a side-effecting tool without an
  `Authorization` (passing gate + approving review, same candidate). This
  turns "zero unapproved actions" from a convention into a structural
  property, and 11 tests make it falsifiable.
- **F021 multi-agent orchestration.** Seven agents, each declaring its
  tools. Two runtimes driving the *same* agents: an in-house graph with
  named routing conditions, cycle detection and a terminal human-review
  interrupt, plus a LangGraph runtime that falls back automatically. The
  run trace is persisted and exposed at `/system/meetings/{id}/agent-run`.
- **F022 composite confidence.** Restored from the archived scorer and
  promoted from display-only to a real gate input: extraction confidence
  blended with owner- and date-resolution quality. This required
  recomputing the score when a reviewer edits an owner — caught by an
  existing test that went red immediately, which is exactly what it was
  written for.
- **F023 code-switch normalization.** Sarvam restored, redesigned as
  *additive*: original text stays verbatim for evidence, translation feeds
  extraction only. The legacy version translated in place, which would
  have silently destroyed every citation on a code-switched transcript.
- **F024–F026 Calendar, memory, notifications.** All three restored as
  gated side effects behind the registry, each independently idempotent
  and audited, each degrading honestly (`skipped` / `failed`) rather than
  taking a successful GitHub issue down with them.
- **F027 live meeting mode.** Websocket session with a rolling window;
  the same commitment heard twice updates one candidate rather than
  duplicating. Every payload states that live mode surfaces only.
- Frontend gained an agent-trace view, a live capture panel, and
  per-approval side-effect selection.
- `verify.sh` gained structural boundary checks; `feature_list.json` gained
  F020–F027; `docs/architecture.md` and `README.md` rewritten.

Test count went 290 → 353. Two failures during the work were genuine and
informative: the legacy-import guard correctly flagged the new `app.agents`
/ `app.tools` packages (the guard was too broad and was narrowed to the
real legacy prototype modules), and the malformed-transcript test caught
that agents now capture errors into state rather than raising — so the
upload route needed to translate a captured error into a 422 instead of
silently returning success.

## Next session

1. Read `AGENTS.md`, `README.md`, `docs/architecture.md`,
   `docs/data-contracts.md`, `feature_list.json`, this file, `git log`.
2. Run `bash init.sh`.
3. **Before anything else: one live end-to-end pass** against real Mongo, a
   real `GROQ_API_KEY`, a sandbox GitHub repo, and — if demoing it —
   Google Calendar credentials. That path is written but unverified.
4. Then `F019`. If a gold transcript has been released, score the Groq
   extractor with `app/services/evaluation.py` before freezing.
