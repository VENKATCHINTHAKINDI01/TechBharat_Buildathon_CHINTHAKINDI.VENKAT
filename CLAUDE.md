# CLAUDE.md

Follow `AGENTS.md` as the primary operating manual.

Before coding:
1. read `AGENTS.md`,
2. run `bash init.sh`,
3. inspect `feature_list.json`,
4. choose one feature only.

Never bypass:
- human approval,
- deterministic safety gates,
- idempotency,
- evidence validation,
- audit logging.

Do not edit more than one feature area in a single session unless the user explicitly asks.