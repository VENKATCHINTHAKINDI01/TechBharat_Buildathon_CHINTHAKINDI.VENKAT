"""
Google Calendar OAuth + low-level API calls.

Uses the Desktop-app InstalledAppFlow (local browser consent, token cached
to disk) rather than a web OAuth callback route. This is a deliberate
simplification for a solo local hackathon build -- you run the backend on
your own machine, authorize once, and token.json persists the session.
GOOGLE_REDIRECT_URI in config.py is unused by this flow; it's kept for a
possible Phase 5+ move to a hosted web OAuth flow, not needed for the demo.

Setup required before first use:
  1. Google Cloud Console -> OAuth consent screen (test mode is fine)
  2. Create OAuth client ID, type "Desktop app"
  3. Download as credentials.json, place at backend/credentials.json
     (gitignored -- never commit this file)
  4. First call to get_calendar_service() opens a browser for consent;
     token.json is written next to credentials.json after that.
"""
import os.path
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
CREDENTIALS_PATH = "credentials.json"
TOKEN_PATH = "token.json"

_service = None


def get_calendar_service():
    global _service
    if _service is not None:
        return _service

    creds = None
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_PATH, "w") as f:
            f.write(creds.to_json())

    _service = build("calendar", "v3", credentials=creds)
    return _service


def create_event(
    summary: str,
    description: str,
    attendee_email: str,
    due_date,  # datetime
    calendar_id: str = "primary",
) -> dict:
    """Creates a single all-day event on `due_date` for exactly one
    attendee -- this is the personalized-per-owner invite, not a
    broadcast to the whole meeting. Returns the created event resource
    (includes 'id', used as calendar_event_id in the notification record)."""
    service = get_calendar_service()
    date_str = due_date.date().isoformat()

    event_body = {
        "summary": summary,
        "description": description,
        "start": {"date": date_str},
        "end": {"date": date_str},
        "attendees": [{"email": attendee_email}],
        "reminders": {"useDefault": True},
    }

    event = service.events().insert(
        calendarId=calendar_id,
        body=event_body,
        sendUpdates="all",  # actually emails the attendee -- this IS the notification
    ).execute()
    return event


def get_event_attendees(event_id: str, calendar_id: str = "primary") -> list[dict]:
    """Pulls the attendee list from an existing Calendar event, for use
    as the owner-resolution roster. Returns [{"name": ..., "email": ...}]."""
    service = get_calendar_service()
    event = service.events().get(calendarId=calendar_id, eventId=event_id).execute()
    attendees = event.get("attendees", [])
    return [
        {"name": a.get("displayName") or a["email"].split("@")[0], "email": a["email"]}
        for a in attendees
    ]