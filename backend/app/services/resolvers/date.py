"""F008: deterministic relative-date resolution against a fixed meeting date.

Uses ``dateparser`` as a pure parsing engine (no network, no LLM) with the
meeting date pinned as the relative base and future-preference enabled, so
"Friday" said on a Wednesday means the upcoming Friday, not last week's.

A small, explicit filler-word list handles common code-switched and
buildathon-transcript phrasing (EOD/COB, "by"/"before"/"on"/"due", time-of-
day words, and the Telugu postpositions "varaku" ("until/by") and "ki"
("to/for") seen in the code-switched fixture) before handing the remainder
to dateparser. This is a controlled, documented lexicon for one language
pair (English + Telugu) per the product brief -- not general NLU. Anything
that still fails to parse resolves to ``None`` / ``unresolved`` rather than
guessing.
"""
from __future__ import annotations

import re
from datetime import date, datetime

import dateparser

from app.domain.models import DateResolutionMethod

_NEXT_WEEKDAY_RE = re.compile(r"\bnext\s+(mon|tues|wednes|thurs|fri|satur|sun)day\b", re.I)
_FILLER_RE = re.compile(
    r"\b(eod|cob|end of day|close of business|by|before|on|due|around|approximately|varaku|ki)\b",
    re.I,
)
_TIME_OF_DAY_RE = re.compile(r"\b(morning|afternoon|evening|night|noon|midnight)\b", re.I)
_ABSOLUTE_DATE_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2})|(\b\d{1,2}/\d{1,2}(/\d{2,4})?\b)|"
    r"(\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\s+\d{1,2}\b)",
    re.I,
)


def _clean(mention: str) -> str:
    s = _NEXT_WEEKDAY_RE.sub(lambda m: m.group(0).split()[-1], mention)
    s = _FILLER_RE.sub(" ", s)
    s = _TIME_OF_DAY_RE.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def resolve_date(mention: str | None, meeting_date: date) -> tuple[date | None, DateResolutionMethod]:
    if not mention or not mention.strip():
        return None, DateResolutionMethod.unresolved

    cleaned = _clean(mention)
    if not cleaned:
        return None, DateResolutionMethod.unresolved

    base_dt = datetime(meeting_date.year, meeting_date.month, meeting_date.day)
    parsed = dateparser.parse(
        cleaned, settings={"RELATIVE_BASE": base_dt, "PREFER_DATES_FROM": "future"}
    )
    if parsed is None:
        return None, DateResolutionMethod.unresolved

    method = (
        DateResolutionMethod.absolute
        if _ABSOLUTE_DATE_RE.search(mention)
        else DateResolutionMethod.relative
    )
    return parsed.date(), method
