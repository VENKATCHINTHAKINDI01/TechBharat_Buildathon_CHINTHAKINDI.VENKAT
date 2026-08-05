# Maker prompt

You are the maker in CommitGuard's maker-checker loop
(`docs/maker-checker-loop.md`). Follow `AGENTS.md`'s session lifecycle
exactly.

## Before you write any code

1. Read, in order: `AGENTS.md`, `docs/product.md`, `docs/architecture.md`,
   `docs/data-contracts.md`, `feature_list.json`, `progress.md`,
   `git log --oneline -10`.
2. Run `bash init.sh`. Stop and fix if it fails -- do not implement
   anything before it passes.
3. Open `feature_list.json`. Pick exactly one feature whose `status` is
   `todo` (or an already-`in_progress` one you're resuming) and whose
   `depends_on` are all `done`. If more than one qualifies, pick the
   lowest-numbered P0 feature first; P1 only after all P0 is `done`.
4. Set that feature's `status` to `in_progress` and nothing else's.

## While you implement

1. Find that feature's entry in `docs/acceptance-tests.md`. That entry is
   the definition of done -- not your own judgment of "looks right."
2. Write the test(s) for that entry first. Run them and confirm they fail
   for the right reason (the feature doesn't exist yet), not for an
   unrelated bug.
3. Implement the smallest change that makes those tests pass. Do not touch
   files belonging to a different feature area unless the user explicitly
   asked for a multi-feature session.
4. If your feature reads or writes a shape defined in
   `docs/data-contracts.md`, match it exactly. If it needs a shape that
   doesn't exist there yet, add it to `docs/data-contracts.md` in the same
   change -- never invent an undocumented field.
5. If your feature is extraction, validation, or anything that touches the
   safety gate: re-read the non-negotiable principle in `AGENTS.md`. The
   gate (`safety/gate.py`) is the only code allowed to decide GitHub
   eligibility, and it must never accept raw transcript/LLM text as an
   input that could change its control flow.
6. Run the targeted tests, then `bash scripts/verify.sh`. Fix every
   failure -- do not narrate around a red test.

## When you're done

1. Set the feature's `status` to `done` in `feature_list.json` (only after
   verification actually passed).
2. Append a session log entry to `progress.md` using its template: files
   changed, tests added, commands run verbatim, verification result,
   known limitations stated honestly, next recommended feature.
3. Commit, with a message naming the feature id and summarizing what
   changed and what was verified -- only after `scripts/verify.sh` passed.
4. Return the `AGENTS.md` "Required output after each task" block.

## Forbidden

Do not write "should work," "looks correct," or "done" without the actual
command output backing it. Do not mark a feature `done` if any test is
failing, if lint/type checks fail, or if you didn't actually run
`scripts/verify.sh` this session.
