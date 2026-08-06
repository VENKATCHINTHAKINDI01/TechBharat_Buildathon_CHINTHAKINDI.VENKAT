# Nexvi.Meets — Maker–Checker Loop

Two roles, one feature at a time, per `AGENTS.md`'s session lifecycle.
Prompts for each role live in `prompts/maker.md` and `prompts/checker.md`.

## Roles

**Maker** — picks exactly one `todo`/`in_progress` feature from
`feature_list.json` in dependency order, writes tests first, implements the
smallest change that satisfies the feature and its entry in
`docs/acceptance-tests.md`, runs targeted tests, then hands off.

**Checker** — receives the maker's diff and claimed evidence, and
independently:

1. Re-reads the feature's entry in `docs/acceptance-tests.md` and confirms
   the tests the maker wrote actually assert what that entry requires (not
   a weaker proxy for it).
2. Re-runs `bash scripts/verify.sh` from a clean checkout rather than
   trusting the maker's reported output.
3. Checks the non-negotiable boundary specifically for any feature that
   touches extraction, validation, or the gate: does anything here let
   LLM-produced or transcript-derived text influence a side-effecting
   decision without passing through `safety/gate.py`?
4. Checks scope: did the maker touch more than one feature area, modify a
   shared schema in `docs/data-contracts.md` without updating that file, or
   add anything not listed in `feature_list.json`?
5. Either approves (feature status -> `done`, `progress.md` updated) or
   sends it back with the specific acceptance-test line that isn't met.

## Current status of this loop

This buildathon session has run as a single agent performing both roles
sequentially and honestly (write tests -> implement -> run -> record
evidence -> only then mark a feature `done`) rather than as two separate
agent invocations. Each feature's commit message in `git log` is the
maker's claimed evidence; `progress.md`'s session log is where checker-style
verification (re-running `scripts/verify.sh`, checking scope) is recorded
against that evidence in the same session.

Splitting this into two literal agent turns (one maker call, one checker
call reviewing the maker's diff before commit) is a reasonable next
hardening step once F011+ introduce state that's expensive to unwind if a
mistake ships (Mongo writes, GitHub issue creation) — see `F011` onward.

## Human approval is a third, non-negotiable role

Neither the maker nor the checker may ever approve a payload for GitHub
creation. That is `docs/product.md`'s human reviewer, enforced structurally
in `F012`'s review API and `F010`'s gate — not a role either agent role
above is permitted to substitute for, per `AGENTS.md`.
