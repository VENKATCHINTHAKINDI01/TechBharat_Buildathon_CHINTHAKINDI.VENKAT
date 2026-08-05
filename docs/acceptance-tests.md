# CommitGuard — Acceptance Tests

One section per feature. Each acceptance test must be automatable (pytest
for backend, a scripted check for repo-level features) and is the bar
`scripts/verify.sh` ultimately enforces for that feature.

## F001 — Repository scaffold and health checks

- `bash init.sh` exits 0 from a clean checkout.
- `bash scripts/verify.sh` exits 0.
- `GET /health` returns HTTP 200 with `status: ok`.
- `GET /commitguard/health` returns HTTP 200 with `status: ok` and
  `component: commitguard`.
- `feature_list.json` is valid JSON and validates against the expected
  shape (project name, non-empty features list, each feature has
  `id`, `priority`, `name`, `status`, `depends_on`).

## F002 — Transcript ingestion for txt/vtt/srt

- Given a `.txt`, `.vtt`, and `.srt` fixture, the ingestion module parses
  each into a common intermediate representation without raising.
- Malformed input raises a typed, caught exception rather than crashing
  the process.

## F003 — Transcript normalization into speaker segments

- Each parsed transcript produces a list of `TranscriptSegment` matching
  `docs/data-contracts.md`, with stable `segment_id`s.

## F004 — Pydantic schemas and JSON validation

- Every schema in `docs/data-contracts.md` has a corresponding Pydantic
  model; round-tripping a valid example through `.model_dump()` /
  `.model_validate()` is lossless.
- Invalid examples (missing required field, wrong enum value) raise
  `ValidationError`.

## F005 — Candidate extraction pass

- Given a fixture transcript, extraction produces `CandidateItem`s whose
  `evidence_quotes[].quote` are verbatim substrings of the referenced
  segment text (enforced by a deterministic check, not the LLM).

## F006 — Commitment validation pass

- A fixture with a suggestion, a confirmed commitment, a disputed claim,
  and a rejection classifies each into the correct `classification` value
  against the evaluation dataset (F016).

## F007 — Participant directory and owner resolution

- Exact-name mentions resolve to the correct participant id.
- Ambiguous or unknown mentions resolve to `null` with
  `owner_resolution_method = unresolved`, never a guess.

## F008 — Relative date resolution

- "next Friday", "by EOD Thursday", "in two weeks" resolve to correct
  ISO dates given a fixed meeting date, across a fixture set.
- Unresolvable date language resolves to `null`, never a guess.

## F009 — Disagreement/cancellation/correction detection (P1)

- A transcript where item B cancels item A sets
  `contradiction_of = A.candidate_id` on B and is excluded from gate
  eligibility.

## F010 — Deterministic safety gate

- Exhaustive table test: for every combination of
  (classification, owner resolved?, evidence present?, contradiction
  present?, confidence vs threshold), the gate's `eligible` output and
  `reasons` match the truth table exactly. This test must not call an LLM.

## F011 — Persistence and audit event store

- Every pipeline stage run against a fixture writes at least one
  `AuditEvent`; the sequence for one meeting is retrievable in order.

## F012 — Human review API

- `GET` candidates for a meeting returns full evidence.
- `POST` a review decision persists it and, for `approved`/
  `edited_and_approved`, requires `final_payload`.
- Attempting to approve a candidate that is not gate-eligible is rejected
  by the API (defense in depth, not just UI-enforced).

## F013 — Review frontend with evidence drawer

- Manual/E2E: reviewer can see each candidate's evidence quotes and
  approve/reject/edit; ineligible candidates are visibly marked as such.

## F014 — GitHub Issues tool behind interface

- The tool is only invoked with an `approved` `ReviewDecision` and a
  gate-`eligible` candidate; a unit test asserts it rejects any other
  input without calling the network.
- GitHub API calls are mocked in tests; no live network calls in CI.

## F015 — Idempotency and duplicate suppression

- Submitting the same approved candidate twice creates exactly one GitHub
  issue; the second attempt is a no-op keyed by `dedupe_key`.

## F016 — Evaluation dataset and scorer

- A labeled fixture set with expected classification/owner/date per item.
- A scorer reports precision/recall on `confirmed` classification, owner
  resolution accuracy, and date resolution accuracy.

## F017 — Code-switched fixture (P1)

- At least one English+Telugu or English+Hindi transcript fixture passes
  through the full pipeline and scores against F016's scorer.

## F018 — End-to-end demo test

- Upload fixture -> extraction -> validation -> resolution -> gate ->
  simulated review approval -> mocked GitHub creation -> idempotent
  re-run, all asserted in one automated test.

## F019 — Evaluation report and demo freeze

- `progress.md` records final scores from F016/F017 and confirms F018
  passes; no further feature work after this without a new session.
