# Nexvi.Meets — Product Spec

Source: *TechBharat Cohort #2 Buildathon Use Cases*, Use Case B ("Agentic
AI Meeting Assistant"). Nexvi.Meets is our entry for that track; the
must-have requirements, constraints, and success metrics in this document
are transcribed from that brief, not invented independently -- see
`progress.md` for the session that reconciled the two.

## Problem

Meeting notes tools summarize conversations but do not distinguish a real
commitment ("I'll ship the migration script by Friday") from a suggestion
("maybe someone should look at that"), a disputed claim, a rejected proposal,
or a commitment that was later cancelled or reassigned. Teams end up with
task trackers full of noise, or worse, silently drop real commitments.

## Product

Nexvi.Meets ingests a meeting transcript and produces a structured meeting
record -- an executive summary, decisions, open questions, risks/blockers,
and **candidate action items** -- where every action item is backed by
verbatim transcript evidence, a resolved owner, a resolved due date, a
priority, and a classification
(`confirmed` / `suggestion` / `disputed` / `rejected` / `cancelled`). A human
reviewer approves or rejects each candidate before anything is created in
GitHub Issues. Nothing reaches GitHub without that approval.

The brief allows integrating with any one of Jira, Linear, Asana, GitHub
Issues, Slack, Teams, Google Calendar, or email, and is explicit that "one
deep, reliable integration beats four shallow ones." Nexvi.Meets's choice
is GitHub Issues (`F014`) -- consistent with `AGENTS.md`'s existing scope
rule against adding Slack/Jira/Calendar/email before all P0/P1 work is
done.

The differentiator is **commitment integrity**, not summarization quality:
Nexvi.Meets would rather surface zero items than surface a wrong owner, a
fabricated date, or a task nobody actually committed to.

## Users

- Meeting organizer / team lead: uploads the transcript, reviews candidates,
  approves the final task list.
- Team members: appear as resolvable owners in the participant directory;
  see their commitments reflected accurately.

## Core user flow

1. Organizer uploads a transcript (`.txt`, `.vtt`, or `.srt`).
2. Nexvi.Meets normalizes it into speaker-attributed segments.
3. An LLM extraction pass proposes candidate items with quotes as evidence.
4. A validation pass classifies each candidate and flags contradictions
   (disagreement, cancellation, reassignment, deadline change).
5. Deterministic resolvers assign one real participant as owner and resolve
   relative dates ("next Friday") against the meeting date.
6. Resolved items are synthesized into one structured meeting record --
   executive summary, decisions, open questions, risks/blockers, action
   items (`F011b`) -- the shape the brief asks for.
7. A deterministic safety gate computes whether each candidate is eligible
   for GitHub creation (see `AGENTS.md` non-negotiable principle).
8. The reviewer sees every candidate — eligible or not — with its evidence,
   in an evidence drawer, and explicitly approves or edits each payload.
9. Only approved payloads reach the GitHub Issues tool. Duplicates (same
   meeting, same owner, same normalized text) are suppressed idempotently.
10. Every extraction, classification, gate decision, approval, and GitHub
    call is recorded in an append-only audit log.

## Explicit non-goals (until P0/P1 are complete)

Live audio, Slack/Jira/Calendar/email integrations, cross-meeting memory,
reminders, and analytics are out of scope. See `AGENTS.md` build priorities.
Audio/video transcription is a brief-allowed stretch ("you own the
transcription step" if attempted) but out of scope until P0/P1 pass --
Nexvi.Meets accepts transcript files (txt/vtt/srt) directly, which the
brief's FAQ explicitly permits ("You can also accept transcripts directly
and skip audio entirely").

## Success criteria

### Buildathon demo (this repo's own bar)

- Upload a fixture transcript with a mix of confirmed commitments,
  suggestions, disputes, and a cancellation.
- Nexvi.Meets extracts and classifies all of them correctly against the
  evaluation dataset (`F016`).
- Only `confirmed`, fully-resolved, evidence-backed, non-contradicted items
  above the confidence threshold are shown as gate-eligible.
- Reviewer approves a subset; approved items appear as real GitHub Issues.
- Re-running the same transcript does not create duplicate issues.
- The audit log shows a complete, inspectable trail for the demo meeting.

### Official TechBharat judging metrics (Use Case B, section B.3)

A gold-standard transcript with human-labelled action items is released at
kickoff; judges run the system against it and against one unseen
transcript. `F016`'s evaluation harness must report against these exact
targets before `F019` (evaluation report and demo freeze):

| Metric | Target | How it's measured |
|---|---|---|
| Action item recall | ≥ 80% of labelled items found | against the gold transcript |
| Action item precision | ≥ 75%, few invented tasks | against the gold transcript |
| Owner accuracy | ≥ 85% correctly attributed | against the gold transcript |
| Date resolution | ≥ 90% of relative dates resolved correctly | spot check of five items |
| End-to-end latency | under 3 minutes for a 45-minute meeting | timed during the demo |
| Unapproved actions | exactly zero | audit log review |
| Duplicate suppression | re-run creates no duplicates | judge runs the same file twice |

### Brief constraints that apply regardless of demo readiness

- No unapproved side effects, ever -- "an agent that emails the wrong
  person fails the track regardless of everything else." This is the same
  non-negotiable principle `AGENTS.md` already states; the brief is where
  it originates.
- A 45-minute meeting must process end to end in under 5 minutes (the
  judging table above is stricter: under 3 minutes).
- Use test/sandbox workspaces for `F014`'s GitHub integration -- never a
  live production tracker for the demo.
- Do not use recordings of real meetings containing confidential or
  personal information without consent. Every fixture in `tests/fixtures/`
  is synthetic for exactly this reason.
- Human approval does not make the system "less agentic" per the brief's
  own FAQ -- "it makes it safe." Auto-send on user opt-in is explicitly
  disallowed for the demo ("Zero unapproved actions is a hard metric on
  this track").
