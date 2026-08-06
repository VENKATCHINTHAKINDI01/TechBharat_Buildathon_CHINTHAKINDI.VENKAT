# Running Nexvi.Meets live

Everything in the test suite runs against in-memory adapters. This
document is the other half: getting the real Mongo, Groq and GitHub paths
running on your machine, in the order where each failure is cheapest to
find.

Do the whole thing **once before the buildathon**, not on the day. Two of
the most likely failures — the Atlas IP allowlist and the Google OAuth
consent screen — depend on the network and browser you are sitting at.

---

## 0. Prerequisites

- Python 3.11+, Node 18+
- A MongoDB Atlas cluster (free tier is fine)
- A Groq API key — <https://console.groq.com/keys>
- A GitHub **fine-grained** personal access token, and a **sandbox repo**

---

## 1. Install

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

cd ../frontend && npm install
```

---

## 2. Configure

```bash
cp backend/.env.example backend/.env
$EDITOR backend/.env
```

The four that must be set:

```ini
MONGO_URI=mongodb+srv://<user>:<password>@<cluster>.mongodb.net/?retryWrites=true&w=majority
GROQ_API_KEY=gsk_...
GITHUB_TOKEN=github_pat_...
GITHUB_REPO=your-name/nexvi_meets_sandbox
```

> **`backend/.env` must never be committed.** It is git-ignored, and
> `scripts/verify.sh` fails the build if it ever becomes tracked.

### The model matters right now

```ini
GROQ_MODEL=openai/gpt-oss-120b
```

`llama-3.3-70b-versatile` **was shut down on 16 August 2026**. If your
`.env` still names it, extraction will fail with a model-not-found error
and silently fall back to the deterministic extractor — which is much
weaker on unseen phrasing and produces no commitment timelines. The
preflight in step 3 fails loudly on this.

### Two settings people get wrong

| Setting | Correct value | Symptom if wrong |
|---|---|---|
| `SARVAM_LANGUAGE_CODE` | `unknown` | Sarvam returns HTTP 400. `auto-detect` is not a value it accepts. |
| `MONGO_DB_NAME` | `nexvi_meets` | Hyphens are invalid in Mongo database names. |

---

## 3. Preflight — do this before anything else

```bash
cd backend
python ../scripts/live_check.py
```

This is the only thing in the repo that touches the real services. It
checks, in order: config → Mongo connect/write/indexes → Groq auth, model
availability and a real extraction → Whisper availability → GitHub read,
issues-enabled, **and an actual issue create** → Sarvam, Chroma, Calendar.

Every failure prints the fix rather than a stack trace. Exit code is 0
only if all required checks passed.

```bash
python ../scripts/live_check.py --skip-github    # don't create the probe issue
python ../scripts/live_check.py --keep-issue     # leave it open to inspect
python ../scripts/live_check.py --skip-optional  # skip Sarvam/Chroma/Calendar
```

The GitHub check **creates a real issue** titled
`[Nexvi.Meets preflight] write check <timestamp>` in your sandbox repo and
closes it again. That is deliberate: a read-only permission check passes
right up until the moment you demo, which is exactly the failure that has
already bitten this project once.

### The three failures you are most likely to hit

**Mongo: SSL handshake / server selection timeout.** The Atlas IP
allowlist. Atlas → Network Access → Add Current IP Address. It changes
when you change networks — re-run the preflight from the venue wifi.

**Mongo: nameservers failed to answer SRV.** DNS, not credentials. Some
corporate networks and VPNs block SRV lookups. Use a phone hotspot, or
the non-SRV connection string from Atlas → Connect → Drivers.

**GitHub 403 "Resource not accessible by personal access token".** The
fine-grained token needs **Issues: Read and write** — repository
permissions, not account permissions. GitHub Settings → Developer
settings → Personal access tokens → Fine-grained tokens → your token →
Repository permissions → Issues → Read and write. A token created before
you granted that permission keeps the old scope; regenerate it.

---

## 4. Run it

Two terminals.

```bash
# terminal 1
cd backend && source .venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

```bash
# terminal 2
cd frontend && npm run dev
```

Open <http://localhost:5173>. The status bar is the ground truth: it
shows **mongo connected**, **groq on**, **github on**. `mongo unreachable`
means the allowlist, not a typo — connection and configuration are
reported separately for exactly that reason.

API docs: <http://localhost:8000/docs>.
Readiness JSON: <http://localhost:8000/readiness>.

---

## 5. The end-to-end pass

### 5a. Upload path (fastest full-loop check)

1. **Upload transcript** → pick `tests/fixtures/owner_reassignment.txt`.
2. Confirm the item shows **History (3)** — proposed → reassigned →
   accepted — and that the owner is **Meera**, not Rohit. If the timeline
   is empty, Groq is not emitting events; check the preflight output.
3. Open **Evidence** and confirm every quote appears in the transcript.
4. Approve one item with `github_issue` ticked. A real issue appears in
   your sandbox repo.
5. Approve the **same** item again → `duplicate_suppressed`, enforced by
   a unique index, not application logic.
6. Open **Past meetings** → the report shows the action taken with a live
   link.

### 5b. Live path

1. **Live meeting** → name the participants → tick the consent box.
2. **Start capturing.** When the share dialog opens, choose the
   **Chrome Tab** option — not Entire Screen — pick your meeting tab, and
   tick **"Also share tab audio"**. That tickbox only exists for a tab;
   without it nobody but you is heard.
3. Pop Naina out with the ⧉ button so she stays on top of the call.
4. Say a commitment out loud. It should appear within ~10 seconds.
5. **Press Pause.** Confirm the browser's recording indicator goes out.
   Say something. Press **Resume** — that sentence must NOT appear, and
   the transcript must show the gap marker.
6. **End & report** → diarization runs, the report generates, and you land
   in review.

Step 5 is the one to actually perform. Pause/resume is covered by
websocket tests but the browser recorder lifecycle has never been
exercised by a real browser.

---

## 6. Before you demo

- [ ] Preflight exits 0 **on the venue network**
- [ ] `GROQ_MODEL=openai/gpt-oss-120b`
- [ ] One Google Calendar invite approved already, so the OAuth consent
      browser flow does not stall the demo
- [ ] `GITHUB_REPO` points at a sandbox — the brief forbids demoing
      against a live tracker
- [ ] Manual-entry fallback rehearsed: live mode accepts typed lines, so
      the demo never hinges on venue audio

---

## Rotate these

Both were pasted in plaintext during development and should be treated as
compromised:

- The MongoDB Atlas password for `venkatstark5_db_user`
- The Sarvam API key

Also replace `0.0.0.0/0` in Atlas Network Access with a specific IP.
