#!/usr/bin/env python3
"""Preflight against the real integrations.

Every other test in this repo runs against in-memory adapters. That is
the right default -- it keeps the suite fast, offline and free -- but it
means the real Mongo, Groq and GitHub paths have never actually run. This
script is the one thing that exercises them, and it is meant to be run
before a demo, on the machine that will do the demoing.

Each check answers one question and, when it fails, says what to change
rather than printing a driver traceback. Failures are ordered by how
early they would bite you: no database means nothing else matters.

    cd backend && python ../scripts/live_check.py

Flags:
    --skip-github     don't create the probe issue
    --skip-optional   Sarvam / Chroma / Calendar only
    --keep-issue      leave the probe issue open (default: closed again)

Exit code is 0 only if every required check passed.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

# Run from anywhere: the backend package is the import root.
BACKEND = Path(__file__).resolve().parent.parent / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

GREEN, RED, YELLOW, DIM, BOLD, RESET = (
    "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[1m", "\033[0m"
)

_results: list[tuple[str, str, str]] = []  # (status, name, detail)


def _record(status: str, name: str, detail: str = "") -> None:
    _results.append((status, name, detail))
    colour = {"PASS": GREEN, "FAIL": RED, "SKIP": YELLOW, "WARN": YELLOW}[status]
    print(f"  {colour}{status:<4}{RESET} {name}")
    if detail:
        for line in detail.strip().splitlines():
            print(f"       {DIM}{line}{RESET}")


def section(title: str) -> None:
    print(f"\n{BOLD}{title}{RESET}")


def _fmt_exc(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"


# --- 1. configuration ------------------------------------------------------


def check_config():
    section("1. Configuration")
    try:
        from app.core.config import get_settings

        settings = get_settings()
    except Exception as exc:
        _record("FAIL", "settings load", _fmt_exc(exc))
        return None

    _record("PASS", "backend/.env parsed")

    missing = [
        name
        for name, value in (
            ("MONGO_URI", settings.mongo_uri),
            ("GROQ_API_KEY", settings.groq_api_key),
            ("GITHUB_TOKEN", settings.github_token),
            ("GITHUB_REPO", settings.github_repo),
        )
        if not value
    ]
    if missing:
        _record("FAIL", "required credentials present", "not set: " + ", ".join(missing))
    else:
        _record("PASS", "required credentials present")

    # The model that shut down on 2026-08-16 is the single most likely
    # cause of a demo failing for a reason nobody changed.
    if settings.groq_model in ("llama-3.3-70b-versatile", "llama-3.1-8b-instant"):
        _record(
            "FAIL",
            f"GROQ_MODEL={settings.groq_model}",
            "This model was shut down on 2026-08-16.\n"
            "Set GROQ_MODEL=openai/gpt-oss-120b in backend/.env",
        )
    else:
        _record("PASS", f"GROQ_MODEL={settings.groq_model}")

    if "/" not in settings.github_repo:
        _record("FAIL", "GITHUB_REPO format", f"expected owner/repo, got {settings.github_repo!r}")
    elif not any(w in settings.github_repo.lower() for w in ("sandbox", "test", "demo")):
        # The brief forbids demoing against a live tracker. This is a
        # nudge, not a blocker -- a repo can be a sandbox without saying so.
        _record(
            "WARN",
            f"GITHUB_REPO={settings.github_repo}",
            "Name doesn't look like a sandbox. Nexvi.Meets creates REAL issues.\n"
            "Confirm this is not a production tracker.",
        )
    else:
        _record("PASS", f"GITHUB_REPO={settings.github_repo}")

    return settings


# --- 2. mongo --------------------------------------------------------------


async def check_mongo(settings) -> bool:
    section("2. MongoDB Atlas")
    try:
        from motor.motor_asyncio import AsyncIOMotorClient
    except ImportError as exc:
        _record("FAIL", "motor installed", _fmt_exc(exc))
        return False

    client = AsyncIOMotorClient(settings.mongo_uri, serverSelectionTimeoutMS=8000)
    started = time.perf_counter()
    try:
        await client.admin.command("ping")
    except Exception as exc:
        text = str(exc).lower()
        if "nameservers failed" in text or "srv" in text and "answer" in text:
            hint = (
                "DNS could not resolve the Atlas SRV record. This is a network\n"
                "problem, not a credentials one -- corporate wifi and some VPNs\n"
                "block SRV lookups. Try a phone hotspot, or use the non-SRV\n"
                "connection string (Atlas -> Connect -> Drivers -> older driver)."
            )
        elif "ssl" in text or "timed out" in text or "serverselection" in text:
            hint = (
                "This is almost always the Atlas IP allowlist.\n"
                "Atlas -> Network Access -> Add IP Address -> Add Current IP Address.\n"
                "Note it changes when you switch networks (venue wifi!)."
            )
        elif "auth" in text:
            hint = "Bad username or password in MONGO_URI.\nAtlas -> Database Access."
        else:
            hint = "Check MONGO_URI is the SRV string from Atlas -> Connect -> Drivers."
        _record("FAIL", "connect", f"{_fmt_exc(exc)}\n\n{hint}")
        client.close()
        return False

    _record("PASS", f"connect ({(time.perf_counter() - started) * 1000:.0f}ms)")

    db = client[settings.mongo_db_name]
    probe = f"preflight-{int(time.time())}"
    try:
        await db.nm_preflight.insert_one({"_id": probe, "at": datetime.now(timezone.utc)})
        await db.nm_preflight.delete_one({"_id": probe})
        _record("PASS", f"write + delete in '{settings.mongo_db_name}'")
    except Exception as exc:
        _record(
            "FAIL",
            "write",
            f"{_fmt_exc(exc)}\n\nThe user can connect but not write.\n"
            "Atlas -> Database Access -> give the user readWrite.",
        )
        client.close()
        return False

    # Idempotency is enforced by unique indexes, not application logic.
    # If they are missing, duplicate suppression silently stops working.
    try:
        from app.main import ensure_indexes  # noqa: F401

        for collection, field in (("nm_issues", "dedupe_key"), ("nm_calendar", "dedupe_key")):
            names = await db[collection].index_information()
            unique = any(
                info.get("unique") and info["key"][0][0] == field for info in names.values()
            )
            if unique:
                _record("PASS", f"unique index {collection}.{field}")
            else:
                _record(
                    "WARN",
                    f"unique index {collection}.{field}",
                    "Missing. It is created on app startup -- start the backend once.\n"
                    "Until then, duplicate suppression is not enforced.",
                )
    except Exception as exc:
        _record("WARN", "index check", _fmt_exc(exc))

    client.close()
    return True


# --- 3. groq ---------------------------------------------------------------

PROBE_TRANSCRIPT = [
    ("Arjun", "Rohit, can you finish the API migration by Friday?"),
    ("Rohit", "Yes, I'll have it done by Friday."),
    ("Rohit", "Actually I'm swamped, Meera could you take it?"),
    ("Meera", "Sure, I can do it. But Thursday, not Friday."),
]


def check_groq(settings) -> bool:
    section("3. Groq — the LLM behind the agents")
    try:
        from groq import Groq
    except ImportError as exc:
        _record("FAIL", "groq package installed", _fmt_exc(exc))
        return False

    try:
        client = Groq(api_key=settings.groq_api_key)
    except Exception as exc:
        _record(
            "FAIL",
            "build Groq client",
            f"{_fmt_exc(exc)}\n\n"
            "Often a proxy setting: check HTTP_PROXY / HTTPS_PROXY / ALL_PROXY.",
        )
        return False

    # Does the configured model actually exist for this key? Cheaper and
    # clearer than discovering it inside a completion.
    try:
        available = {m.id for m in client.models.list().data}
    except Exception as exc:
        text = str(exc).lower()
        hint = (
            "Invalid API key. Get a new one at https://console.groq.com/keys"
            if "401" in text or "invalid" in text
            else "Check network access to api.groq.com."
        )
        _record("FAIL", "authenticate", f"{_fmt_exc(exc)}\n\n{hint}")
        return False

    _record("PASS", f"authenticate ({len(available)} models available)")

    if settings.groq_model not in available:
        close = sorted(m for m in available if "gpt-oss" in m or "qwen" in m)
        _record(
            "FAIL",
            f"model '{settings.groq_model}' available",
            "Your key cannot use this model.\nTry one of: " + ", ".join(close),
        )
        return False
    _record("PASS", f"model '{settings.groq_model}' available")

    # The real extractor, on a transcript whose correct answer we know.
    from app.domain.models import TranscriptSegment
    from app.services.extraction.groq import GroqExtractor

    segments = [
        TranscriptSegment(
            segment_id=f"probe-{i:03d}", speaker=speaker, text=text,
            start_ms=i * 8000, end_ms=(i + 1) * 8000,
        )
        for i, (speaker, text) in enumerate(PROBE_TRANSCRIPT)
    ]

    started = time.perf_counter()
    extractor = GroqExtractor(settings=settings, client=client)
    try:
        items = extractor.extract(segments, "probe")
    except Exception as exc:
        _record(
            "FAIL",
            "extraction",
            f"{_fmt_exc(exc)}\n\n"
            "This is the failure that makes a live meeting report\n"
            "'no candidates extracted' -- the app falls back to the\n"
            "pattern-based extractor, which finds almost nothing in\n"
            "natural speech.",
        )
        return False

    elapsed = time.perf_counter() - started
    if not items:
        _record("FAIL", "extraction found the commitment", f"returned 0 items in {elapsed:.1f}s")
        return False
    _record("PASS", f"extraction returned {len(items)} item(s) in {elapsed:.1f}s")

    # The probe transcript is a renegotiation: Rohit accepts, hands to
    # Meera, Meera accepts different terms. Getting Meera/Thursday right
    # is the whole product working end to end.
    item = items[0]
    states = [e["state"] for e in item.timeline]
    if states:
        _record("PASS", f"commitment timeline: {' -> '.join(states)}")
    else:
        _record(
            "WARN",
            "commitment timeline",
            "Groq returned no timeline events, so the state engine has nothing to show.\n"
            "The model may be ignoring the timeline field. Extraction still works.",
        )

    owner = (item.raw_owner_mention or "").lower()
    if "meera" in owner:
        _record("PASS", "final owner is Meera (not Rohit)")
    else:
        _record(
            "WARN",
            "final owner",
            f"got {item.raw_owner_mention!r}, expected Meera.\n"
            "The model missed the reassignment. Not fatal -- the reviewer can fix it.",
        )

    date_mention = (item.raw_date_mention or "").lower()
    if "thursday" in date_mention:
        _record("PASS", "final date is Thursday (not Friday)")
    else:
        _record("WARN", "final date", f"got {item.raw_date_mention!r}, expected Thursday")

    # The quietest way to lose a whole meeting: the model answers, but
    # quotes words nobody said, so every action item is dropped by the
    # citation check and the queue comes up empty with no explanation.
    from app.services.extraction.base import EvidenceReport, drop_unsupported_evidence

    report = EvidenceReport()
    survivors = drop_unsupported_evidence(items, segments, report)

    if report.dropped_items:
        _record(
            "FAIL",
            "evidence quotes are real",
            f"{len(report.dropped_items)} of {len(items)} item(s) were dropped because the\n"
            f"model quoted words that are not in the transcript.\n"
            f"e.g. {report.examples[0] if report.examples else ''}\n\n"
            "This is what produces an empty review queue on a meeting that\n"
            "clearly contained commitments.",
        )
        return False

    detail = ""
    if report.quotes_repaired:
        detail = (
            f"{report.quotes_repaired} quote(s) matched only after normalising\n"
            "typography (curly apostrophes, dashes). Handled automatically."
        )
    _record("PASS", f"all {report.quotes_kept} evidence quote(s) verified", detail)
    _record("PASS", f"{len(survivors)} item(s) survive the full pipeline")

    return True


def check_groq_stt(settings) -> None:
    section("4. Groq Whisper — live transcription")
    try:
        from groq import Groq

        client = Groq(api_key=settings.groq_api_key)
        available = {m.id for m in client.models.list().data}
    except Exception as exc:
        _record("SKIP", "whisper", f"could not reach Groq: {_fmt_exc(exc)}")
        return

    if settings.groq_transcription_model in available:
        _record("PASS", f"model '{settings.groq_transcription_model}' available")
        _record(
            "WARN",
            "actual transcription untested",
            "Only a browser can produce the audio this path takes.\n"
            "Verify by running a real live meeting (step 5 in the runbook).",
        )
    else:
        _record(
            "FAIL",
            f"model '{settings.groq_transcription_model}' available",
            "Set GROQ_TRANSCRIPTION_MODEL=whisper-large-v3-turbo",
        )


# --- 5. github -------------------------------------------------------------


async def check_github(settings, keep_issue: bool) -> bool:
    section("5. GitHub Issues")
    import httpx

    from app.adapters.trackers.github import describe_token, explain_github_failure

    _record("PASS", f"token looks {describe_token(settings.github_token)}")

    headers = {
        "Authorization": f"Bearer {settings.github_token}",
        "Accept": "application/vnd.github+json",
    }
    base = f"{settings.github_api_base}/repos/{settings.github_repo}"

    try:
        client_cm = httpx.AsyncClient(timeout=20)
    except Exception as exc:
        _record(
            "FAIL",
            "build HTTP client",
            f"{_fmt_exc(exc)}\n\n"
            "Often a proxy setting: check HTTP_PROXY / HTTPS_PROXY / ALL_PROXY.",
        )
        return False

    async with client_cm as client:
        try:
            response = await client.get(base, headers=headers)
        except Exception as exc:
            _record("FAIL", "reach api.github.com", _fmt_exc(exc))
            return False

        if response.status_code != 200:
            _record(
                "FAIL",
                "repository readable",
                explain_github_failure(
                    response.status_code, response.text, settings.github_repo,
                    settings.github_token,
                ),
            )
            return False

        repo = response.json()
        _record("PASS", f"repository readable ({'private' if repo.get('private') else 'public'})")

        if not repo.get("has_issues", True):
            _record(
                "FAIL",
                "issues enabled",
                "Settings -> General -> Features -> tick 'Issues'.",
            )
            return False
        _record("PASS", "issues enabled")

        # The only real proof the token can write. A read-only check
        # passes right up until the demo, which is exactly what happened
        # last time.
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        try:
            created = await client.post(
                f"{base}/issues",
                headers=headers,
                json={
                    "title": f"[Nexvi.Meets preflight] write check {stamp}",
                    "body": (
                        "Automated preflight probe from `scripts/live_check.py`.\n\n"
                        "Confirms the configured token can create issues in this "
                        "repository. Safe to delete."
                    ),
                    "labels": ["nexvi-preflight"],
                },
            )
        except Exception as exc:
            _record("FAIL", "create issue", _fmt_exc(exc))
            return False

        if created.status_code not in (200, 201):
            _record(
                "FAIL",
                "create issue",
                explain_github_failure(
                    created.status_code, created.text, settings.github_repo,
                    settings.github_token,
                ),
            )
            return False

        issue = created.json()
        _record("PASS", f"create issue -> {issue['html_url']}")

        if keep_issue:
            _record("SKIP", "close probe issue", "--keep-issue was passed")
        else:
            closed = await client.patch(
                f"{base}/issues/{issue['number']}", headers=headers, json={"state": "closed"}
            )
            if closed.status_code == 200:
                _record("PASS", f"closed probe issue #{issue['number']}")
            else:
                _record("WARN", "close probe issue", f"HTTP {closed.status_code}; close it by hand")

    return True


# --- 6. optional integrations ---------------------------------------------


def check_optional(settings) -> None:
    section("6. Optional integrations")

    if settings.sarvam_api_key:
        import httpx

        try:  # noqa: SIM105 -- client construction can throw on proxy config
            response = httpx.post(
                f"{settings.sarvam_api_base}/translate",
                headers={"api-subscription-key": settings.sarvam_api_key},
                json={
                    "input": "Monday varaku share chesthava?",
                    "source_language_code": settings.sarvam_language_code,
                    "target_language_code": "en-IN",
                    "model": settings.sarvam_model,
                },
                timeout=20,
            )
            if response.status_code == 200:
                _record("PASS", "Sarvam translate")
            else:
                _record("WARN", "Sarvam translate", f"HTTP {response.status_code}: {response.text[:200]}")
        except Exception as exc:
            _record("WARN", "Sarvam translate", _fmt_exc(exc))
    else:
        _record("SKIP", "Sarvam", "SARVAM_API_KEY not set — transcripts used verbatim")

    if settings.chroma_api_key:
        try:
            import chromadb

            chromadb.CloudClient(
                api_key=settings.chroma_api_key,
                tenant=settings.chroma_tenant,
                database=settings.chroma_database,
            ).heartbeat()
            _record("PASS", "ChromaDB Cloud")
        except Exception as exc:
            _record("WARN", "ChromaDB Cloud", f"{_fmt_exc(exc)}\nMemory indexing will report 'skipped'.")
    else:
        _record("SKIP", "ChromaDB", "CHROMA_API_KEY not set — memory effect reports 'skipped'")

    credentials = Path(BACKEND / settings.google_credentials_path)
    if credentials.exists():
        _record("PASS", f"Google credentials at {settings.google_credentials_path}")
        token = Path(BACKEND / settings.google_token_path)
        if not token.exists():
            _record(
                "WARN",
                "Google OAuth token",
                "Not yet granted. The first calendar_invite opens a browser consent\n"
                "flow, which will stall a live demo. Approve one invite beforehand.",
            )
    else:
        _record("SKIP", "Google Calendar", "no credentials.json — calendar effect reports 'skipped'")


# --- main ------------------------------------------------------------------


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-github", action="store_true")
    parser.add_argument("--skip-optional", action="store_true")
    parser.add_argument("--keep-issue", action="store_true")
    args = parser.parse_args()

    print(f"{BOLD}Nexvi.Meets — live integration preflight{RESET}")
    print(f"{DIM}{datetime.now().strftime('%Y-%m-%d %H:%M')} · {date.today()}{RESET}")

    settings = check_config()
    if settings is None:
        return 1

    mongo_ok = await check_mongo(settings)
    groq_ok = check_groq(settings)
    check_groq_stt(settings)

    if args.skip_github:
        section("5. GitHub Issues")
        _record("SKIP", "github", "--skip-github was passed")
        github_ok = True
    else:
        github_ok = await check_github(settings, args.keep_issue)

    if not args.skip_optional:
        check_optional(settings)

    failures = [r for r in _results if r[0] == "FAIL"]
    warnings = [r for r in _results if r[0] == "WARN"]

    print(f"\n{BOLD}{'─' * 60}{RESET}")
    if failures:
        print(f"{RED}{BOLD}{len(failures)} check(s) failed.{RESET} Fix these before demoing:")
        for _, name, _detail in failures:
            print(f"  {RED}·{RESET} {name}")
        return 1

    summary = f"{GREEN}{BOLD}All required checks passed.{RESET}"
    if warnings:
        summary += f" {YELLOW}{len(warnings)} warning(s) — read them.{RESET}"
    print(summary)
    print(
        f"{DIM}Mongo {'ok' if mongo_ok else '--'} · "
        f"Groq {'ok' if groq_ok else '--'} · "
        f"GitHub {'ok' if github_ok else '--'}{RESET}"
    )
    print(
        f"\n{DIM}Still unverified by this script: real browser audio capture,\n"
        f"pause/resume, and the human approval flow. Run a live meeting.{RESET}"
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        sys.exit(130)
