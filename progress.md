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

Verification: `bash scripts/verify.sh` exits 0; **447 tests pass** with no
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
cd backend && pytest -q tests       -> 447 passed
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

### 2026-08-06 — Session 7 (audit; identity, reports, history, floating bar)

A full audit of every agent, tool and endpoint. One serious bug found.

- **F031 meeting identity — SERIOUS BUG FIXED.** Live meeting ids were
  `f"live-{id(websocket) & 0xFFFFFF:06x}"`. CPython reuses memory
  addresses, so consecutive short-lived sockets collide: measured
  **19,999 collisions in 20,000 objects**. Two live meetings in a row
  would have shared an id — and the id keys the audit trail, the dedupe
  keys, review decisions and issue records, so meeting two's commitments
  would have merged into meeting one and one meeting's approval could
  satisfy another's idempotency check. Replaced with
  `nm-YYYYMMDD-<10 hex>` from uuid4, plus a repository existence check.
  200,000 generated ids, zero collisions.
- **F032 end-of-meeting report.** Generated when a meeting ends and
  regenerated on every open, so a report read a week later reflects
  approvals made since rather than freezing at the moment the call
  dropped. Includes what was actually created, read from the side-effect
  ledgers rather than the audit narrative — plus refusals and failures,
  which leave no ledger entry and would otherwise make the report
  quietly optimistic. Markdown export for pasting into Slack.
- **F033 history + action ledger.** `GET /meetings` now returns
  server-aggregated counts newest-first (fifty meetings would otherwise
  be fifty round trips), plus `/actions`, `/transcript` and `/report.md`
  per meeting. Transcripts are persisted so reports stay rebuildable.
- **F034 floating bar.** Document Picture-in-Picture overlay showing the
  live transcript and detected commitments in an OS-level always-on-top
  window — the only mechanism that stays visible while you are in the
  Meet tab. React renders into it through a portal, so it is the same
  component tree with no message passing. Draggable in-page fallback for
  browsers without the API, honest that it only floats above this tab.

Audit result: 7 agents, 17 tools (exactly 4 side-effecting), all four
side effects firing and independently idempotent, 13 audit stages
recorded, cross-meeting memory recalling, live sessions producing
distinct ids and reviewable candidates after the call. 399 -> 432 tests.

### 2026-08-06 — Session 8 (human override; the gate had a dead end)

Reported: vague group statements ("Everyone should finish by the
weekend", "Priya and Arjun should complete their tasks") were all blocked
as `suggestion`, with no way forward. The request was to loosen the gate.

The gate's verdict was *correct* -- nobody individually committed -- but
the product was still failing the user, in a way worth recording:

**There was no path from "blocked" to "approved".** `EditRequest` had no
`classification` field, so a reviewer who knew Arjun really took the item
could not say so. Worse, even fixing owner AND date left the score at
0.70 against a 0.75 threshold, because the model's original 0.40 still
dominated the blend. A reviewer could do everything right and stay
blocked. That is a dead end, not caution.

Fixed by adding a human override rather than weakening the gate:

- `EditRequest.classification` lets a reviewer correct the model's
  reading, in both directions (confirm a suggestion, or downgrade an
  over-eager `confirmed`).
- `ResolvedItem.human_confirmed` records that a person vouched for it,
  and `compute_confidence` lets that *replace* the extraction component
  entirely. Someone who was in the room outranks the extractor's guess.
- Audited as `human_override: true` with the reviewer's name.

**The six rules are untouched.** Confirming alone does not approve
anything: an item still needs an owner, a resolved date, evidence, no
contradiction, and a passing threshold. Reclassifying to `cancelled`
still blocks. Tests assert both directions, including that a cancelled
item stays unapprovable.

UI: blocked items now read "Needs your input before anything can be
created" with a note that the item is captured either way, plus a
checkbox to confirm a commitment. They were reading as failures when
they are really captured notes awaiting a decision.

439 -> 447 tests.

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

### 2026-08-05 — Session 8 (commitment state engine, Naina, recording controls)

**F035 commitment state engine.** A commitment is no longer a
classification extracted once; it is a thread of timestamped events, each
carrying the verbatim line that caused it. `current_state`,
`current_owner`, `current_due_date` and the classification the gate reads
are all *derived* from that thread, so they cannot drift out of sync with
the evidence.

The rule the engine exists to enforce: **any change to the terms requires
fresh acceptance.** A reassigned or postponed task leaves `accepted` and
sits in a pending state until the new owner agrees to the new terms.
Nobody is bound to a commitment they did not make. That is stricter than
most tools and it is deliberate — the product's whole claim is commitment
integrity, and inheriting an acceptance across changed terms would quietly
break it.

This also closes a limitation carried since session 3: renegotiated
threads used to collapse into a single candidate with the reason in a
free-text `contradiction_note`, and the specified `contradiction_of`
lineage field was never once populated. Both are replaced by the sequence
itself. Verified against the fixtures:

| Fixture | Timeline |
|---|---|
| `confirmed_commitment.txt` | proposed → accepted |
| `deadline_change.txt` | proposed → accepted → deadline changed → accepted |
| `owner_reassignment.txt` | proposed → reassigned → accepted |
| `cancelled_commitment.txt` | proposed → accepted → cancelled |

**F036 per-field confidence.** One blended number told a reviewer to be
nervous without telling them what to fix. Confidence is now split across
wording / owner / date / agreement, and the gate names the weakest field
in its block reason ("weakest: owner at 0.30") instead of printing a
composite.

**F037 Naina.** The assistant now has a name and a consistent presence —
the floating panel, the setup screen, the transcript gap markers and the
report all speak as her. Deliberately restrained: she narrates what she is
doing and never claims to have done anything the human did not approve.

**F038 pause and resume.** Pause stops capture on both tracks and
disables the media tracks, so the browser's recording indicator goes out —
the signal other participants can actually see. Ordering matters and is
tested: recorders stop *first*, then the server is told, so a chunk still
in flight arrives before the server flips state and is dropped there.
Resume inserts a visible gap marker rather than letting the transcript
jump silently.

Two things worth recording about the marker:

1. It is stored in the transcript but **excluded from extraction**.
   Feeding it to the extractor would let Naina cite her own words as
   evidence for a commitment. There is a test for exactly that.
2. Pause deliberately discards the in-flight chunk instead of flushing
   it. That chunk contains audio from the moment the person reached for
   the button, which is the moment they wanted stopped.

**A flaky test, fixed honestly.** `test_ids_do_not_collide_at_scale` drew
200,000 ids from a 40-bit space and asserted zero collisions. By the
birthday bound that fails ~2% of runs — it was asserting something untrue,
and it duly failed once during this session with nothing changed. It now
asserts what is actually true and actually matters (collisions negligible
at a scale far past any real deployment), and `unique_meeting_id` re-draws
against the repository anyway, so a collision costs a round trip rather
than a merged meeting.

Test count 452 → 479. Frontend builds clean.

### 2026-08-06 — Session 9 (Groq timelines, model migration, live preflight)

**The Groq model was 11 days from dying.** `llama-3.3-70b-versatile` was
deprecated on 2026-06-17 with a shutdown date of **2026-08-16**. It still
worked, so nothing looked wrong — the failure would have arrived
mid-buildathon with nobody having changed a line. Migrated to
`openai/gpt-oss-120b`, Groq's own recommended replacement: faster (500 vs
280 t/s), cheaper on both input and output, and production-tier rather
than preview. The preflight now fails loudly on either shut-down model ID.

**F039 Groq emits commitment timelines.** Previously only the
deterministic extractor produced events, which meant the state engine —
the session-8 centrepiece — was dead on the primary path. The prompt now
asks for a per-item event list with a worked renegotiation example, and
every event clears two deterministic filters the model cannot influence:

1. the quote must be a verbatim substring of the segment it cites, the
   same standard `drop_unsupported_evidence` applies to evidence;
2. the transition must be legal under `LEGAL_TRANSITIONS`.

So a confused model produces a **shorter** thread, never a wrong one.
Where the model's claimed classification contradicts its own timeline
("confirmed" on a thread ending at `reassigned`), the timeline wins,
because it is the part backed by quotes — and `suggestion` is the
direction that cannot reach GitHub. The thread's final owner and date
also override the model's summary fields, which tend to be filled from
the first mention rather than the last.

**F040 live preflight.** `scripts/live_check.py` is the only thing in the
repo that touches real services. It checks config → Mongo connect, write
and unique indexes → Groq auth, model availability and a real extraction
on a known renegotiation → Whisper availability → GitHub read,
issues-enabled and an **actual issue create-and-close** → Sarvam, Chroma,
Calendar. Per the user's decision it really does write to GitHub: a
read-only check passes right up until the demo, which is precisely the
failure that already bit this project once.

Building it caught two things worth recording. Its first version died
with a traceback when the sandbox's SOCKS proxy broke httpx client
construction — a diagnostic tool that crashes is the thing it exists to
prevent, so every client construction is now guarded and reported as one
more line. And DNS SRV failure needed separating from the Atlas IP
allowlist: both look like "cannot reach Mongo" but have completely
different fixes.

Test count 479 → 488. Still true, and still the biggest risk: **no live
run has actually succeeded yet.** The preflight has only ever been run
from a sandbox with no network route to any of the three services.

### 2026-08-06 — Session 10 (the first live meeting, and why it produced nothing)

The first real live meeting captured a transcript and then reported **"No
candidates were extracted from this transcript"**, with a structured
record of all zeros. The full suite was green at the time. That gap
between "tests pass" and "works end to end" is the whole story of this
session.

**The bug was not the failure. It was the silence.** Three completely
different situations produced that identical screen:

1. the LLM call failed and `live.py` swallowed `ExtractionError`, falling
   through to the pattern-based extractor, which finds almost nothing in
   natural speech;
2. the LLM answered but paraphrased its citations, so every action item
   was dropped by `drop_unsupported_evidence`;
3. the meeting genuinely contained no commitments.

The fallback is correct behaviour and stays. What was wrong is that it
was invisible: no warning, no log line, no audit entry. `live.py` now
records the extractor used, the actual error, and what the citation check
removed; all of it reaches the websocket snapshot, the audit log, and a
new `extraction` block on the meeting detail API. The review screen
renders a different explanation for each of the three cases instead of
one ambiguous sentence.

**F042 evidence matching.** The citation check demanded an exact
substring. Whisper emits curly apostrophes and em dashes; a model quoting
that text back almost always straightens them. Every such quote was being
treated as a hallucination, which silently destroyed correct action
items. Matching now folds both sides — NFKC, unified quotes and dashes,
collapsed whitespace, case — but **returns the span from the segment**,
via an index map back through the folding. So the guarantee is unchanged:
what a reviewer sees is literally the speaker's words, never the model's
rendering of them. A genuine paraphrase still fails, and there are tests
for exactly that boundary.

**Groq structured output.** `openai/gpt-oss-120b` supports `json_schema`
with `strict: true` — constrained decoding, so the API cannot return
malformed JSON at all. The extractor now sends a full schema on models
that support it and falls back to `json_object` on a 400. Non-400 errors
stop immediately rather than burning a second call, and the failure
message now names the model and every attempt.

**Two mistakes worth recording.** Wiring the diagnostics I called
`repository.list_audit_events`, which does not exist — and my own
`try/except` swallowed the `AttributeError` and returned empty
diagnostics. I had reproduced the exact bug I was fixing, in the fix.
Second, I initially reached for a `note_call` shortcut that would have
bypassed the tool registry; the report is now threaded through
`grade_evidence` as an out-parameter so the tool-call trail stays intact.

**F041 also added a full-journey test** — upload, review, gate, approve,
idempotency, report, history, audit, agent run — because every seam was
individually green while the path between them was broken.

Test count 488 → 514. A 20-check end-to-end smoke over the real API
passes 20/20.

## Next session

1. Read `AGENTS.md`, `README.md`, `docs/architecture.md`,
   `docs/data-contracts.md`, `feature_list.json`, this file, `git log`.
2. Run `bash init.sh`.
3. **Before anything else: one live end-to-end pass** against real Mongo, a
   real `GROQ_API_KEY`, a sandbox GitHub repo, and — if demoing it —
   Google Calendar credentials. That path is written but unverified. It
   now also needs a real pause/resume during that pass: the recorder
   lifecycle is only exercised by tests, never by a browser.
4. Then `F019`. If a gold transcript has been released, score the Groq
   extractor with `app/services/evaluation.py` before freezing.
5. The Groq extractor does not yet emit `timeline` events — only the
   deterministic reference extractor does. Groq-extracted items fall back
   to a single derived state, so the timeline UI stays empty on that path.
   Worth closing before the demo if Groq is the primary extractor.
