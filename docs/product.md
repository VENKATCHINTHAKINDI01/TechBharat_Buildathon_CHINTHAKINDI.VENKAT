# CommitGuard — Product Spec

## Problem

Meeting notes tools summarize conversations but do not distinguish a real
commitment ("I'll ship the migration script by Friday") from a suggestion
("maybe someone should look at that"), a disputed claim, a rejected proposal,
or a commitment that was later cancelled or reassigned. Teams end up with
task trackers full of noise, or worse, silently drop real commitments.

## Product

CommitGuard ingests a meeting transcript and produces a reviewable list of
**candidate action items**, each backed by verbatim transcript evidence, a
resolved owner, a resolved due date, and a classification
(`confirmed` / `suggestion` / `disputed` / `rejected` / `cancelled`). A human
reviewer approves or rejects each candidate before anything is created in
GitHub Issues. Nothing reaches GitHub without that approval.

The differentiator is **commitment integrity**, not summarization quality:
CommitGuard would rather surface zero items than surface a wrong owner, a
fabricated date, or a task nobody actually committed to.

## Users

- Meeting organizer / team lead: uploads the transcript, reviews candidates,
  approves the final task list.
- Team members: appear as resolvable owners in the participant directory;
  see their commitments reflected accurately.

## Core user flow

1. Organizer uploads a transcript (`.txt`, `.vtt`, or `.srt`).
2. CommitGuard normalizes it into speaker-attributed segments.
3. An LLM extraction pass proposes candidate items with quotes as evidence.
4. A validation pass classifies each candidate and flags contradictions
   (disagreement, cancellation, reassignment, deadline change).
5. Deterministic resolvers assign one real participant as owner and resolve
   relative dates ("next Friday") against the meeting date.
6. A deterministic safety gate computes whether each candidate is eligible
   for GitHub creation (see `AGENTS.md` non-negotiable principle).
7. The reviewer sees every candidate — eligible or not — with its evidence,
   in an evidence drawer, and explicitly approves or edits each payload.
8. Only approved payloads reach the GitHub Issues tool. Duplicates (same
   meeting, same owner, same normalized text) are suppressed idempotently.
9. Every extraction, classification, gate decision, approval, and GitHub
   call is recorded in an append-only audit log.

## Explicit non-goals (until P0/P1 are complete)

Live audio, Slack/Jira/Calendar/email integrations, cross-meeting memory,
reminders, and analytics are out of scope. See `AGENTS.md` build priorities.

## Success criteria (buildathon demo)

- Upload a fixture transcript with a mix of confirmed commitments,
  suggestions, disputes, and a cancellation.
- CommitGuard extracts and classifies all of them correctly against the
  evaluation dataset (`F016`).
- Only `confirmed`, fully-resolved, evidence-backed, non-contradicted items
  above the confidence threshold are shown as gate-eligible.
- Reviewer approves a subset; approved items appear as real GitHub Issues.
- Re-running the same transcript does not create duplicate issues.
- The audit log shows a complete, inspectable trail for the demo meeting.
