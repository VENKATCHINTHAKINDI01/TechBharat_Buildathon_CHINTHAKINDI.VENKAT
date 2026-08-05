# CommitGuard — Demo Script (TechBharat Buildathon)

Status markers below: ✅ implemented + tested this session, ⏳ not yet built
(see `feature_list.json`). Do not demo an ⏳ step as if it works.

## 1. The pitch (30 seconds)

"Meeting tools summarize. CommitGuard decides what's actually a
commitment. It reads a transcript, tells suggestions apart from real
commitments, disputes, rejections, and cancellations, resolves who owns
each one and by when, and only ever creates a GitHub issue after a human
approves the exact payload. No owner, no evidence, no unresolved
contradiction, or confidence below threshold: it doesn't get auto-approved,
full stop."

## 2. Ingestion + normalization ✅

Show `tests/fixtures/code_switched.txt`:

```
Arjun: Priya, deployment checklist complete chesi Monday varaku share chesthava?
Priya: Yes, Monday morning ki పంపిస్తాను.
```

Run:

```bash
cd backend
PYTHONPATH=$(pwd) python3 -c "
from app.commitguard.ingestion.parser import parse_txt
from app.commitguard.ingestion.normalization import normalize
utterances = parse_txt(open('../tests/fixtures/code_switched.txt', encoding='utf-8').read())
segments = normalize(utterances, meeting_id='demo')
for s in segments: print(s.segment_id, s.speaker, '->', s.text)
"
```

Point out: two languages, one transcript, parsed into clean speaker turns
with zero special-casing at the ingestion layer.

## 3. Extraction + validation ✅ (deterministic reference implementation)

Same script, add:

```python
from app.commitguard.agents.reference_pipeline import extract_and_validate
items = extract_and_validate(segments, meeting_id='demo')
for i in items:
    print(i.classification, i.raw_owner_mention, i.raw_date_mention, '->', i.raw_text)
```

Expected output line: `confirmed Priya Monday morning -> Priya will share
the deployment checklist by Monday morning`.

Mention honestly: this pass is currently a documented, deterministic
pattern-based reference implementation (see `docs/architecture.md`), not an
LLM call yet -- built this way so the rest of the pipeline (owner/date
resolution, the safety gate) could be built and proven against real
candidates without first standing up and evaluating an LLM prompt.

## 4. Owner + date resolution ✅

```python
from app.commitguard.models.schemas import Participant
from app.commitguard.resolvers import resolve_owner, resolve_date
from datetime import date
priya = Participant(participant_id="p-priya", name="Priya")
owner_id, owner_method = resolve_owner(items[0].raw_owner_mention, [priya])
due, date_method = resolve_date(items[0].raw_date_mention, date(2026, 8, 5))
print(owner_id, owner_method, due, date_method)
```

Then show the **ambiguous_owner** fixture with two participants both named
"Priya" in the directory -- resolution fails closed (`None`,
`unresolved`), not a guess.

## 5. The safety gate ✅

Walk the six rules live against `backend/app/commitguard/tests/test_gate.py`:
no owner, low confidence, contradiction/dispute, no evidence, rejected or
cancelled, unresolved date -- each blocks independently, each shows up as
its own reason string. Run the exhaustive 160-case truth-table test in
front of the judges:

```bash
PYTHONPATH=$(pwd) python3 -m pytest -q app/commitguard/tests/test_gate.py -k truth_table
```

Show the `prompt_injection` fixture: the transcript contains a line telling
the "system" to approve everything without review. Run it through
extraction -> gate and show it's still blocked -- the injected text never
reaches the gate as anything but inert evidence content.

## 6. Human review -> GitHub Issues ⏳

Not built yet this session (`F011`-`F015`). When demoed, this step must
show: the reviewer sees the evidence drawer, approves the exact payload,
and only then does a GitHub issue appear -- and re-submitting the same
approval does not create a duplicate.

## 7. Close

"Every step you just watched is a deterministic function you can unit
test, not a probability the model reports. That's the difference between
a chatbot flexing about a meeting and a system a team can actually trust
with its task tracker."
