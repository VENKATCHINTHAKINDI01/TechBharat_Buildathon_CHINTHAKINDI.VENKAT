# Progress Log

## Current state

Eleven features done: repository scaffold, ingestion (txt/vtt/srt) +
normalization, schemas, participant/date resolution, a deterministic
reference extraction+validation pass (F005/F006/F009 combined), the
six-rule deterministic safety gate (F010), plus two brief-compliance
patches added mid-session after the official TechBharat Cohort #2 brief
(PDF) was uploaded and read in full: F004b (action item `priority` field)
and F011b (structured `MeetingRecord` synthesis: executive summary +
decisions + open questions + risks/blockers + action items). CommitGuard
is built inside the existing `backend/app/commitguard/`;
`frontend/src/commitguard/` starts at F013. Not yet built: persistence/
audit store, human review API, review frontend, GitHub Issues tool,
idempotency, evaluation harness, E2E test, demo freeze (F011, F012-F019).

## Last verified commit

HEAD at end of this session (`git log --oneline -1` from repo root, commit
message reconciling docs against the official brief -- see git log for the
exact hash). Full history this session, oldest to newest:
chore(scaffold) -> F001 -> F004 -> F002+F003 -> F007 -> F008 ->
F005+F006+F009 -> F010 -> docs -> F004b -> F011b -> docs (brief
reconciliation).

## Active feature

None (F001-F010, F004b, F011b closed out; next pick is F011).

## Completed features

- F001 — Repository scaffold and health checks.
- F002 — Transcript ingestion for txt/vtt/srt.
- F003 — Transcript normalization into speaker segments.
- F004 — Pydantic schemas and JSON validation.
- F004b — Action item priority field (TechBharat brief compliance patch).
- F005 — Candidate extraction pass (deterministic reference implementation).
- F006 — Commitment validation pass (deterministic reference implementation).
- F007 — Participant directory and owner resolution.
- F008 — Relative date resolution.
- F009 — Disagreement, cancellation, and correction detection.
- F010 — Deterministic safety gate.
- F011b — Structured meeting record synthesis.

## Verification evidence

- `bash init.sh` — exit 0, full output ends `Initialization complete.`
  (re-run at the very end of this session, after all nine features landed).
- `bash scripts/verify.sh` — exit 0, full output ends
  `verify.sh: all checks passed`.
- `cd backend && PYTHONPATH=$(pwd) python3 -m pytest -q app/commitguard/tests`
  — **232 passed**, 0 failed, across:
  - `test_scaffold.py` (3) — F001
  - `test_schemas.py` (11) — F004
  - `test_ingestion.py` (19) — F002/F003, all 9 named fixtures parse
  - `test_owner_resolution.py` (8) — F007, incl. ambiguous_owner fixture
  - `test_date_resolution.py` (11) — F008, incl. code-switched date phrase
  - `test_extraction_validation.py` (10) — F005/F006/F009, all 9 fixtures
  - `test_gate.py` (170) — F010, incl. exhaustive 160-case truth table
- Confirmed red-then-green on F001's health check (404 before mounting,
  200 after) and on F005/F006 (vague_suggestion fixture initially produced
  2 candidates instead of 1 -- a false-positive suggestion trigger on
  Rohit's "Yeah, maybe." reply -- fixed by narrowing `SUGGESTION_HEDGES` to
  require "someone should" rather than firing on standalone "maybe").
- Manually ran the demo-script.md walkthrough for the code-switched fixture
  and confirmed the printed output matches what's documented there
  (`confirmed Priya "Monday morning ki" -> "Priya will share the deployment
  checklist by Monday morning"`).

## Known failures / limitations

- No git history existed before this session; `git init` was required.
  This environment's mounted workspace filesystem does not permit
  unlinking newly-created files (blocks git's lock-file protocol) until
  file-delete permission is explicitly granted for the folder — flagging
  this because it will bite the next session too if delete permission
  resets.
- The sandbox's system Python (3.10) needed `pyopenssl`/`cryptography`
  upgraded and the full `backend/requirements.txt` installed via
  `pip install --break-system-packages` before `app.main` would import;
  the repo's own `venv/` is a macOS build and is not usable from this
  Linux sandbox. No requirements.txt content changed — this is an
  environment note, not a code fix.
- `scripts/verify.sh`'s pytest step is scoped to `app/commitguard`, not
  the pre-existing `backend/tests/*.py` files (those are empty stubs
  predating this harness and belong to later features, e.g. F005/F006).
- No lint/type-check step is wired into `scripts/verify.sh` yet — no
  linter/formatter config exists in the repo. Should be added by whichever
  feature first introduces non-trivial logic (likely F002 or F004).
- CommitGuard has no Mongo collections or persistence yet (F011). Nothing
  in F001-F010 touches the database.
- **F005/F006 are a deterministic reference implementation, not an LLM
  call.** `docs/architecture.md` records this as a deliberate scoping
  decision: it unblocked F007-F010 without first standing up and
  evaluating a Groq-backed extraction prompt. It recognizes a fixed,
  documented set of English phrases plus a small controlled Telugu lexicon
  (`chesthava`, `chesthanu`, `పంపిస్తాను`, postpositions `ki`/`varaku`) --
  it is not general NLU and will misclassify phrasing outside the fixture
  set. One rewrite (`_CHECKLIST_CHESI_RE` in `reference_pipeline.py`) is a
  hand-written special case targeting the exact flagship demo phrase from
  the product brief, not a general translation capability -- flagged
  in-line in the code, not hidden.
- The gate's contradiction rule (rule 3) treats `contradiction_of` set on
  an already-`confirmed` item as resolved lineage, not a block -- this is
  a narrower reading than data-contracts.md's original "(or resolved)"
  phrasing, which didn't specify what "resolved" means operationally. This
  session's reference extractor never actually sets `contradiction_of`
  (deadline-change/reassignment threads collapse to a single final
  candidate instead of two linked ones); `contradiction_note` is used for
  human-readable context instead. Worth revisiting once F011's audit store
  needs real before/after lineage.
- No lint/type-check step is wired into `scripts/verify.sh` yet — no
  linter/formatter config exists in the repo.
- Owner/date resolvers and the gate are unit-tested directly; there is no
  wired-up single function yet that runs ingestion -> extraction -> owner
  resolution -> date resolution -> gate end-to-end over a fixture in one
  call (that's F018's job, once F011-F017 exist). Today it's demonstrated
  manually, as in `docs/demo-script.md`.

## Files changed this session (cumulative, F001 through the docs commit)

- Root harness: `AGENTS.md`, `feature_list.json`, `init.sh`, `progress.md`,
  `docs/product.md`, `docs/architecture.md`, `docs/data-contracts.md`,
  `docs/acceptance-tests.md`, `docs/maker-checker-loop.md`,
  `docs/demo-script.md`, `prompts/maker.md`, `prompts/checker.md`,
  `scripts/verify.sh`.
- Fixtures: `tests/fixtures/` — `confirmed_commitment.txt`,
  `vague_suggestion.txt`, `owner_reassignment.txt`, `deadline_change.txt`,
  `disagreement.txt`, `cancelled_commitment.txt`, `ambiguous_owner.txt`,
  `prompt_injection.txt`, `code_switched.txt`, `malformed.txt`,
  `sample.vtt`, `sample.srt`.
- `backend/app/commitguard/`:
  - `__init__.py`, `routes.py` (F001)
  - `models/__init__.py`, `models/schemas.py` (F004)
  - `ingestion/__init__.py`, `ingestion/parser.py`,
    `ingestion/normalization.py` (F002/F003)
  - `resolvers/__init__.py`, `resolvers/owner_resolver.py`,
    `resolvers/date_resolver.py` (F007/F008)
  - `agents/__init__.py`, `agents/reference_pipeline.py` (F005/F006/F009)
  - `safety/__init__.py`, `safety/gate.py` (F010)
  - `config.py` (F010, confidence threshold)
  - `tests/` — `test_scaffold.py`, `test_schemas.py`, `test_ingestion.py`,
    `test_owner_resolution.py`, `test_date_resolution.py`,
    `test_extraction_validation.py`, `test_gate.py`
- `backend/app/main.py` — two lines: import + mount of `commitguard_router`
  at prefix `/commitguard`; existing Nexvi.Meets routes untouched.
- `.git/` initialized at repo root (was not previously a git repo).

## Tests added

232 tests total in `backend/app/commitguard/tests/` (see "Verification
evidence" above for the per-file breakdown).

## Next session

1. Read `AGENTS.md`, `docs/product.md`, `docs/architecture.md`,
   `docs/data-contracts.md`, `feature_list.json`, `progress.md`,
   `git log --oneline -10`.
2. Run `bash init.sh`.
3. Start `F011` (persistence and audit event store) — the only remaining
   feature whose dependencies are already `done`. Everything past it
   (`F012`-`F019`) is gated behind it or `F014`/`F011` together.
4. `F016` (evaluation dataset and scorer) is the natural point to decide
   whether the F005/F006 reference implementation gets replaced by an
   LLM-backed one, or kept and scored as the baseline -- read the
   "F005/F006 implementation note" in `docs/architecture.md` before
   deciding. It's also where the official brief's numeric targets
   (`docs/product.md`, "Official TechBharat judging metrics") get
   measured for the first time.
5. Do not touch F001-F011b's files without a reason recorded here.

## Session log template

### Date:
### Agent/tool:
### Feature:
### Files changed:
### Tests added:
### Commands run:
### Verification result:
### Known limitations:
### Handoff:

## Session log

### Date: 2026-08-05
### Agent/tool: Claude (Cowork)
### Feature: F001 — Repository scaffold and health checks
### Files changed: see "Files changed this session" above
### Tests added: see "Tests added" above
### Commands run:
```
bash init.sh
bash scripts/verify.sh
cd backend && PYTHONPATH=$(pwd) python3 -m pytest -q app/commitguard/tests
```
### Verification result: `init.sh` exit 0; `scripts/verify.sh` exit 0;
3/3 targeted tests passed; health test was red before the router was
mounted and green after.
### Known limitations: see "Known failures / limitations" above.
### Handoff: F001 done. F002 and F004 are both unblocked next; F002
(ingestion) is the recommended next pick since F005 needs both F003 and
F004, and F003 needs F002.

### Date: 2026-08-05
### Agent/tool: Claude (Cowork)
### Feature: F004 — Pydantic schemas and JSON validation
### Files changed: `backend/app/commitguard/models/{__init__.py,schemas.py}`,
`backend/app/commitguard/tests/test_schemas.py`, `feature_list.json`
### Tests added: 11 tests in `test_schemas.py` — round-trip for every
shape in `docs/data-contracts.md`, `ValidationError` on missing/invalid
fields, `action_item` candidates requiring non-empty evidence.
### Commands run: `PYTHONPATH=$(pwd) python3 -m pytest -q app/commitguard/tests/test_schemas.py`
### Verification result: 11/11 passed.
### Known limitations: none new.
### Handoff: F002/F003 next (both depend only on F001/F004, both now done).

### Date: 2026-08-05
### Agent/tool: Claude (Cowork)
### Feature: F002 — Transcript ingestion (txt/vtt/srt) + F003 — normalization
### Files changed: `backend/app/commitguard/ingestion/{__init__.py,parser.py,normalization.py}`,
`backend/app/commitguard/tests/test_ingestion.py`, `tests/fixtures/*` (12 new
files: 9 named fixtures + malformed.txt + sample.vtt + sample.srt),
`feature_list.json`
### Tests added: 19 tests — format parsing for txt/vtt/srt, typed
`TranscriptParseError` on malformed input (not a crash), stable
`segment_id` assignment, verbatim preservation of the Telugu text in the
code-switched fixture.
### Commands run: `PYTHONPATH=$(pwd) python3 -m pytest -q app/commitguard/tests/test_ingestion.py`
### Verification result: 19/19 passed on first run after fixtures were written.
### Known limitations: the txt "Speaker: text" convention is the only
supported line format; vtt/srt speaker attribution falls back to the same
convention when there's no `<v Speaker>` tag.
### Handoff: F007 next (owner resolution, depends only on F004).

### Date: 2026-08-05
### Agent/tool: Claude (Cowork)
### Feature: F007 — Participant directory and owner resolution
### Files changed: `backend/app/commitguard/resolvers/{__init__.py,owner_resolver.py}`,
`backend/app/commitguard/tests/test_owner_resolution.py`, `feature_list.json`
### Tests added: 8 tests — exact match (name/alias, case-insensitive),
fuzzy match (rapidfuzz, typo tolerance), unresolved on unknown mention,
unresolved on `None`, and the ambiguous_owner case (two participants both
named "Priya" -> unresolved unless an alias disambiguates).
### Commands run: `PYTHONPATH=$(pwd) python3 -m pytest -q app/commitguard/tests/test_owner_resolution.py`
### Verification result: 8/8 passed on first run.
### Known limitations: fuzzy threshold (85, WRatio) and clear-winner margin
(10 points) are hand-picked constants, not tuned against a labeled dataset
-- that tuning belongs to F016.
### Handoff: F008 next (date resolution, also depends only on F004).

### Date: 2026-08-05
### Agent/tool: Claude (Cowork)
### Feature: F008 — Relative date resolution
### Files changed: `backend/app/commitguard/resolvers/date_resolver.py`,
`backend/app/commitguard/resolvers/__init__.py` (added export),
`backend/app/commitguard/tests/test_date_resolution.py`, `feature_list.json`
### Tests added: 11 tests — weekday resolution relative to a fixed
Wednesday meeting date, EOD/time-of-day stripping, "in two weeks", the
code-switched fixture's "Monday morning ki" phrase, the Telugu "varaku"
postposition, absolute-date detection, and `None`/empty/unresolvable
phrases all returning `(None, unresolved)`.
### Commands run: `PYTHONPATH=$(pwd) python3 -m pytest -q app/commitguard/tests/test_date_resolution.py`
### Verification result: 11/11 passed after calibrating the filler-word
regex against real `dateparser` output (documented via ad hoc scripts, not
committed) -- "next Friday" needed the leading "next" stripped before a
bare weekday name because `dateparser` in this environment returns `None`
for "next Friday" as-is.
### Known limitations: the filler/postposition lexicon is hand-curated for
this fixture set, not exhaustive; genuinely ambiguous phrases ("in a few
days") intentionally resolve to `None` rather than guess.
### Handoff: F005/F006 next (extraction + validation) -- both now unblocked
since F003 and F004 are done.

### Date: 2026-08-05
### Agent/tool: Claude (Cowork)
### Feature: F005 — Candidate extraction pass, F006 — Commitment
validation pass, F009 — Disagreement/cancellation/correction detection
(implemented together as one deterministic reference pipeline; see
"F005/F006 implementation note" in `docs/architecture.md`)
### Files changed: `backend/app/commitguard/agents/{__init__.py,reference_pipeline.py}`,
`backend/app/commitguard/tests/test_extraction_validation.py`,
`docs/architecture.md` (new section documenting the interface decision),
`feature_list.json`
### Tests added: 10 tests, one per named fixture plus a cross-fixture
verbatim-evidence check.
### Commands run: `PYTHONPATH=$(pwd) python3 -m pytest -q app/commitguard/tests/test_extraction_validation.py`,
then the full suite.
### Verification result: 9/10 passed on first run; one failure
(vague_suggestion producing 2 candidates instead of 1, because "maybe" in
Rohit's one-word reply also matched the suggestion-hedge trigger) fixed by
narrowing the trigger to "someone should" only. 10/10 after the fix; full
suite 62/62 at that point.
### Known limitations: see "Known failures / limitations" above --
deterministic, not an LLM; controlled English+Telugu lexicon only, per the
product brief's "support one pair properly" instruction; one hand-written
special case for the flagship demo phrase.
### Handoff: F010 next (safety gate), now unblocked (F006/F007/F008 done).

### Date: 2026-08-05
### Agent/tool: Claude (Cowork)
### Feature: F010 — Deterministic safety gate
### Files changed: `backend/app/commitguard/safety/{__init__.py,gate.py}`,
`backend/app/commitguard/config.py` (new: `CommitGuardSettings.confidence_threshold`),
`backend/app/commitguard/tests/test_gate.py`, `feature_list.json`
### Tests added: 170 tests -- 160-case exhaustive truth table
(`classification x owner_resolved x evidence_present x contradiction_set x
confidence_ok x date_resolved`), one targeted test per rule, a signature
test proving `check_gate` cannot structurally accept raw transcript text,
and a timestamp sanity check.
### Commands run: `PYTHONPATH=$(pwd) python3 -m pytest -q app/commitguard/tests/test_gate.py`,
then the full suite.
### Verification result: two rounds of failures fixed before green --
(1) the truth-table's `_make_item` helper used `kind="action_item"`, which
the F004 schema validator rejects when `evidence_quotes` is empty, breaking
every `evidence_present=False` case; fixed by using `kind="decision"` in
the test helper. (2) the signature test assumed a live class annotation,
but `reference_pipeline.py`'s `from __future__ import annotations` makes
`ResolvedItem`'s annotation a string at runtime; fixed the test to handle
both forms. 170/170 after both fixes; full suite 232/232.
### Known limitations: the "contradiction detected" rule only blocks on
`classification == disputed` or `contradiction_of` set on a non-confirmed
item -- see "Known failures / limitations" above for why, and what F011
needs to revisit.
### Handoff: F011 (persistence and audit event store) is the only
remaining feature with all dependencies (`F004`) already done. F016
(evaluation dataset and scorer) is the natural point to score the F005/F006
reference implementation and decide whether to keep or replace it with an
LLM.

### Date: 2026-08-05
### Agent/tool: Claude (Cowork)
### Feature: F004b — Action item priority field; F011b — Structured
meeting record synthesis; docs reconciliation against the official
TechBharat Cohort #2 Buildathon Use Cases PDF (uploaded and read in full
this session -- Use Case B, "Agentic AI Meeting Assistant", is
CommitGuard's actual brief)
### Files changed:
- `backend/app/commitguard/models/schemas.py` — `Priority` enum,
  `CandidateItem.priority`; `MeetingRecord` model
- `backend/app/commitguard/models/__init__.py` — export `Priority`,
  `MeetingRecord`
- `backend/app/commitguard/agents/reference_pipeline.py` — `_derive_priority`,
  applied at all three `ValidatedItem` construction sites
- `backend/app/commitguard/agents/meeting_record.py` (new) —
  `synthesize_meeting_record`, `_build_executive_summary`
- `backend/app/commitguard/agents/__init__.py` — export
  `synthesize_meeting_record`
- `backend/app/commitguard/resolvers/combine.py` (new) —
  `resolve_validated_item(s)`, the first glue wiring F006's output through
  F007+F008 into a real `ResolvedItem`
- `backend/app/commitguard/resolvers/__init__.py` — export the above
- `backend/app/commitguard/tests/test_priority_field.py` (new, 4 tests)
- `backend/app/commitguard/tests/test_meeting_record.py` (new, 8 tests)
- `docs/data-contracts.md` — `priority` field + F004b section on
  `CandidateItem`; new `MeetingRecord` section
- `docs/acceptance-tests.md` — F004b section; F011b section; corrected
  F009's acceptance criteria to describe `contradiction_note` (what's
  actually implemented) instead of `contradiction_of` (what was originally
  speced but not what F009 actually does -- see limitations below)
- `docs/product.md` — brief source citation; official B.3 success-metrics
  table (recall/precision/owner accuracy/date resolution/latency/
  unapproved-actions/duplicate-suppression) with exact targets; brief
  constraints (sandbox workspace, no real recordings without consent,
  human approval doesn't reduce agency); executive summary in the product
  description and core user flow
- `feature_list.json` — new `F004b`, `F011b` entries, both `done`
### Tests added: 12 new tests (4 + 8); full commitguard suite grew from
232 to 244.
### Commands run:
```
bash init.sh
bash scripts/verify.sh
cd backend && PYTHONPATH=$(pwd) python3 -m pytest -q app/commitguard/tests
```
### Verification result: 244/244 passed; `init.sh` and `scripts/verify.sh`
both exit 0 from the fully built state. No regressions in the pre-existing
232 tests from adding the `priority` field (default value keeps round-trip
tests equal).
### Known limitations:
- The official brief's numeric judging targets (recall ≥80%, precision
  ≥75%, owner accuracy ≥85%, date resolution ≥90%) are now documented in
  `docs/product.md`, but nothing scores CommitGuard against them yet --
  that's `F016` (evaluation dataset and scorer), still `todo`. The
  deterministic reference implementation's actual recall/precision on a
  labelled set is unmeasured.
- `synthesize_meeting_record`'s executive summary is a deterministic
  template (counts + a semicolon-joined list of confirmed commitments),
  not natural prose -- same documented tradeoff as F005/F006.
- Found and fixed a real spec/implementation mismatch while re-reading
  `docs/acceptance-tests.md` against what F009 actually does: the original
  acceptance criteria said cancellation "sets `contradiction_of` on B" --
  the actual reference implementation never sets `contradiction_of` (it
  collapses renegotiated threads into one final candidate and uses
  `contradiction_note` instead, per the F010 session's known-limitations
  note). Fixed the doc to describe reality rather than silently leaving a
  false acceptance criterion in place.
- Brief items still not reflected in any feature: diarization (brief says
  "either from provided labels or through diarization" -- CommitGuard
  currently only supports provided labels, which the brief explicitly
  allows), and the brief's "at least one genuine side effect" requirement
  is only satisfied once `F014` (GitHub Issues tool) actually lands, not
  yet.
### Next recommended feature: F011 (persistence and audit event store) --
unblocks F012 (human review API), which is the dependency root for
everything from F013 through F019.
