# Progress Log

## Current state

**Complete, runnable end-to-end product.** Every P0 and P1 feature is `done`
except `F019` (evaluation report and demo freeze). A transcript can be
uploaded, extracted, classified, resolved, gated, reviewed by a human, and
turned into a real GitHub issue that cannot be duplicated — with a full
audit trail, through the API and through the React UI.

Verification: `bash scripts/verify.sh` exits 0; **290 tests pass** with no
network access and no credentials; the frontend builds clean.

## Active feature

None. Next pick is `F019`.

## Completed features

F001 scaffold · F002 ingestion · F003 normalization · F004 schemas ·
F004b priority field · F005 extraction · F006 validation · F007 owner
resolution · F008 date resolution · F009 disagreement/cancellation ·
F010 safety gate · F011 persistence + audit · F011b meeting record ·
F012 review API · F013 review frontend · F014 GitHub Issues ·
F015 idempotency · F016 evaluation harness · F017 code-switched fixture ·
F018 end-to-end test.

## Verification evidence

```
bash scripts/verify.sh              -> exit 0, "verify.sh: all checks passed"
cd backend && pytest -q tests       -> 290 passed
cd frontend && npm run build        -> built in 567ms, no errors
```

Test breakdown (290):

| Suite | N | Covers |
|---|---|---|
| `unit/test_gate.py` | 170 | F010, incl. exhaustive 160-case truth table |
| `unit/test_ingestion.py` | 19 | F002/F003, all 9 fixtures + malformed/vtt/srt |
| `unit/test_schemas.py` | 11 | F004 round-trip + validation errors |
| `unit/test_date_resolution.py` | 11 | F008, incl. Telugu postpositions |
| `unit/test_groq_extractor.py` | 11 | Groq parsing, stubbed client, no network |
| `unit/test_extraction_validation.py` | 10 | F005/F006/F009 across all fixtures |
| `unit/test_meeting_record.py` | 8 | F011b partition + summary |
| `unit/test_owner_resolution.py` | 8 | F007 incl. ambiguous-owner fail-closed |
| `unit/test_evidence_filter.py` | 6 | citation grading |
| `unit/test_idempotency.py` | 6 | F015 dedupe key properties |
| `unit/test_priority_field.py` | 4 | F004b |
| `unit/test_evaluation.py` | 4 | F016 scorer + measured baseline |
| `integration/test_review_flow.py` | 21 | F012/F014/F015/F018 full HTTP flow |
| `integration/test_scaffold.py` | 4 | F001 + legacy-import guard |

Evaluation (F016), deterministic extractor against `tests/fixtures/labels.json`:

| Metric | Result | Brief target | Pass |
|---|---|---|---|
| Action item recall | 87.5% | ≥ 80% | yes |
| Action item precision | 100% | ≥ 75% | yes |
| Owner accuracy | 100% | ≥ 85% | yes |
| Date resolution | 100% | ≥ 90% | yes |
| Gate decisions vs. labels | 100% | — | — |

The single recall miss is `disagreement.txt` → "roll back the deploy": the
system classifies it as a `decision` (disputed), not an `action_item`, so
it isn't counted as found. Arguably the label is wrong rather than the
system — left as a visible miss rather than adjusted to manufacture 100%.

## Known limitations — read before demoing

- **The evaluation numbers above are on fixtures we wrote *and* labelled
  ourselves.** They are not the judges' gold transcript. The deterministic
  extractor is pattern-based; on unseen phrasing it will score far lower.
  This is precisely why Groq is the primary extractor whenever a key is
  present — but the Groq path's accuracy is **unmeasured**, because we have
  no gold transcript to measure it against.
- The deterministic reference extractor recognizes a fixed set of English
  phrases plus a documented Telugu lexicon (`chesthava`, `chesthanu`,
  `పంపిస్తాను`, `ki`, `varaku`). One rewrite (`_CHECKLIST_CHESI_RE`) is a
  hand-written special case targeting the brief's flagship demo sentence —
  flagged in the code, not hidden. It is not general NLU.
- **No end-to-end run has been executed against real Mongo, real Groq, or
  real GitHub in this environment.** All 290 tests use in-memory adapters
  and a stubbed Groq client. The real adapters are written and typed but
  their live behaviour is unverified — this is the highest-risk gap before
  a demo. Run once against a sandbox repo before presenting.
- Latency against the brief's "under 3 minutes for a 45-minute meeting"
  target is unmeasured; no transcript of that size has been run.
- `contradiction_of` is never populated by the reference extractor;
  renegotiated threads collapse into one final candidate and use
  `contradiction_note` for human-readable context. The gate handles both,
  but true before/after lineage doesn't exist yet.
- No lint or type-check step is wired into `scripts/verify.sh` — the repo
  has no ruff/mypy config. Worth adding before the codebase grows further.
- Audio transcription and diarization are not implemented (both explicitly
  permitted by the brief's FAQ). Cross-meeting memory, reminders, Slack/
  Jira/Calendar, and live mode are P2 and deliberately absent.
- The frontend has no automated tests; it is verified by `npm run build`
  and manual use only.

## Session log

### 2026-08-05 — Sessions 1–3 (harness through brief reconciliation)

Built the harness (`AGENTS.md`, `feature_list.json`, `init.sh`,
`scripts/verify.sh`, `docs/*`), then F001–F010 in dependency order, each
with tests written first and verification recorded before the feature was
marked `done`. Notable red-then-green moments: F001's health check (404
before mounting), F005/F006 (`vague_suggestion` produced 2 candidates until
`SUGGESTION_HEDGES` was narrowed to "someone should"), F010 (the truth-table
helper used `kind="action_item"`, which the F004 validator rejects with
empty evidence). After the official TechBharat brief PDF was supplied, added
F004b (`priority`) and F011b (`MeetingRecord`) to close two real compliance
gaps, and corrected `docs/acceptance-tests.md`, which had described F009 as
setting `contradiction_of` — behaviour the implementation never had.

### 2026-08-05 — Session 4 (restructure + complete the product)

**Structural decision:** the repo contained two parallel half-implementations
of the same product. The legacy Nexvi.Meets pipeline could reach a real
external side effect (a Calendar invite) with **no safety gate at all**,
directly contradicting the brief's hard "zero unapproved actions" metric.
Per the user's decision, the useful parts were absorbed and the rest
archived to `legacy/` rather than deleted, with `legacy/README.md`
documenting each file's disposition. A test
(`test_app_does_not_import_legacy_nexvi_modules`) now fails if any of it
re-enters the import graph.

Restructured into ports-and-adapters: `core` / `domain` / `services` /
`adapters` / `api`, with `tests/{unit,integration}`. All 245 existing tests
stayed green through the move.

Then built the remaining features:

- **F011** — `Repository` protocol; Mongo implementation with a **unique
  index** on `cg_issues.dedupe_key` so duplicate suppression holds under
  concurrent approvals, not just in application logic; in-memory
  implementation for tests. Append-only audit writer.
- **F014/F015** — `IssueTracker` protocol; real GitHub REST implementation;
  in-memory test double. Dedupe key now hashes the **resolved owner id**
  rather than the spoken name, so "Rohit"/"rohit"/"Rohit Sharma" cannot
  produce three issues for one commitment.
- **Groq extractor** — primary when a key is present, deterministic
  fallback otherwise. The prompt demands segment-cited verbatim quotes;
  unknown enum values coerce toward `suggestion` (never toward
  `confirmed`), so a confused model degrades into "needs a human" rather
  than "ship it".
- **`drop_unsupported_evidence`** — deterministic citation grading applied
  to *every* extractor's output. An LLM does not get to grade its own
  citations.
- **F012** — review API. Editing mutates the **item**, not the payload, so
  the gate re-evaluates the corrected values; a reviewer cannot hand-write
  a payload past a gate that never saw it. `approval.py` re-runs the gate
  server-side at the moment of the side effect rather than trusting the
  UI's last render.
- **F013** — React review UI: status bar showing live integrations, meeting
  record, candidate cards with gate reasons, evidence drawer showing the
  verbatim quotes and the exact JSON payload, edit/approve/reject, and the
  full audit table.
- **F016/F018** — labelled eval dataset + scorer reporting the brief's four
  metrics; 21 integration tests covering ineligible/cancelled/disputed/
  prompt-injection refusals, duplicate suppression, tracker-failure
  auditing, edit-then-approve, and the code-switched meeting end to end.

Also: `README.md` (was empty), `backend/.env.example`, `backend/Dockerfile`,
rewritten `docker-compose.yml` and `docs/architecture.md`, cleaned
`requirements.txt` (dropped chroma/langgraph/sarvam/google — all archived),
and `scripts/verify.sh` now additionally checks dependency ordering in
`feature_list.json`, that `backend/.env` is untracked, that labelled
fixtures exist on disk, and that live code never imports `legacy/`.

## Next session

1. Read `AGENTS.md`, `README.md`, `docs/architecture.md`,
   `docs/data-contracts.md`, `feature_list.json`, this file, `git log`.
2. Run `bash init.sh`.
3. **Before anything else: run one live end-to-end pass** against real
   Mongo, a real `GROQ_API_KEY`, and a sandbox GitHub repo. That path is
   written but unverified, and it is the biggest risk to the demo.
4. Then `F019` (evaluation report and demo freeze) — and if a gold
   transcript has been released, score the Groq extractor against it with
   `app/services/evaluation.py` before freezing.
