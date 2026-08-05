from datetime import datetime

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.db.mongo import get_db
from app.models.meeting import Meeting
from app.roster.attendee_roster import build_roster

# Routers
from app.review.routes import router as review_router

app = FastAPI(title="NexVi.Meets", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(review_router, prefix="/review", tags=["review"])


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health", tags=["health"])
async def health():
    settings = get_settings()
    return {"status": "ok", "app": settings.app_name, "environment": settings.environment}


# ---------------------------------------------------------------------------
# Phase 4: file-upload pipeline entrypoint (with roster support)
# ---------------------------------------------------------------------------

@app.post("/meetings/upload", tags=["meetings"])
async def upload_meeting(
    file: UploadFile = File(...),
    title: str = Form(...),
    meeting_date: str = Form(...),  # ISO date string, e.g. "2026-08-05"
    calendar_event_id: str | None = Form(None),  # pull roster from this Calendar event, if given
    manual_attendees: str | None = Form(None),  # newline-separated "Name <email>" fallback
):
    """
    File -> ingestion -> extraction -> resolution -> dedup -> Mongo, with
    status="pending_review" on every action item.

    Roster priority: calendar_event_id (real attendee list) > manual_attendees
    (typed fallback) > empty (every item will fail-loud on owner resolution --
    expected behavior, not a bug, when neither source is provided).
    """
    from app.agents.graph import run_pipeline

    raw_bytes = await file.read()
    try:
        raw_text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(400, "Could not decode file as UTF-8 text")

    try:
        parsed_date = datetime.fromisoformat(meeting_date)
    except ValueError:
        raise HTTPException(400, "meeting_date must be ISO format, e.g. 2026-08-05")

    manual_list = manual_attendees.splitlines() if manual_attendees else None
    try:
        attendees = build_roster(calendar_event_id, manual_list)
    except Exception as exc:  # noqa: BLE001 -- Calendar API failure shouldn't block upload
        raise HTTPException(502, f"Could not build attendee roster: {exc}")

    db = get_db()
    meeting = Meeting(
        title=title,
        meeting_date=parsed_date,
        source="file",
        attendees=attendees,
    )

    result_state = await run_pipeline({
        "filename": file.filename,
        "raw_text": raw_text,
        "meeting_id": None,
        "meeting": meeting,
        "meeting_date": parsed_date,
        "attendees": attendees,
        "db": db,
    })

    if result_state.get("error"):
        raise HTTPException(422, result_state["error"])

    return {
        "meeting_id": result_state["meeting_id"],
        "action_items_saved": len(result_state.get("saved_action_item_ids", [])),
        "executive_summary": result_state["structured_record"].executive_summary,
    }