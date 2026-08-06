"""Google Calendar client.

Restored from ``legacy/nexvi_meets/backend/integrations/google_calendar_client.py``
with three changes:

1. It is async at the seam (the Google SDK is synchronous, so the blocking
   call runs in a thread) — the rest of the app is async and should not be
   stalled by an HTTP round trip.
2. It never invents a due date. The legacy version defaulted a missing
   deadline to "tomorrow"; CommitGuard's gate already refuses to approve an
   item with an unresolved date, so a missing date here is a bug worth
   raising rather than papering over.
3. Failures raise ``CalendarError`` instead of returning partial results.

Setup (same as before):
  1. Google Cloud Console -> OAuth consent screen (test mode is fine)
  2. Create an OAuth client ID of type "Desktop app"
  3. Download as ``backend/credentials.json`` (gitignored, never committed)
  4. First call opens a browser for consent; ``token.json`` is cached beside it
"""
from __future__ import annotations

import asyncio
import os

from app.adapters.calendar.base import CalendarError, CalendarInvite, CreatedEvent
from app.core.config import Settings, get_settings

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]

_service = None


def _build_service(settings: Settings):
    global _service
    if _service is not None:
        return _service

    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise CalendarError(
            "Google Calendar libraries are not installed. "
            "pip install -r backend/requirements.txt"
        ) from exc

    creds = None
    if os.path.exists(settings.google_token_path):
        creds = Credentials.from_authorized_user_file(settings.google_token_path, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        elif os.path.exists(settings.google_credentials_path):
            flow = InstalledAppFlow.from_client_secrets_file(
                settings.google_credentials_path, SCOPES
            )
            creds = flow.run_local_server(port=0)
        else:
            raise CalendarError(
                f"Google OAuth client file not found at "
                f"{settings.google_credentials_path}. Download the 'Desktop app' "
                "OAuth client from Google Cloud Console and place it there, or "
                "disable the calendar_invite side effect."
            )
        with open(settings.google_token_path, "w", encoding="utf-8") as handle:
            handle.write(creds.to_json())

    _service = build("calendar", "v3", credentials=creds)
    return _service


class GoogleCalendarClient:
    name = "google_calendar"

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def _create_sync(self, invite: CalendarInvite) -> CreatedEvent:
        if invite.due_date is None:
            raise CalendarError(
                "Refusing to create a calendar invite without a resolved due date. "
                "The safety gate should have blocked this item; if you are seeing "
                "this, the gate was bypassed."
            )
        service = _build_service(self._settings)
        day = invite.due_date.isoformat()
        body = {
            "summary": invite.summary,
            "description": invite.description,
            "start": {"date": day},
            "end": {"date": day},
            "attendees": [{"email": invite.attendee_email}],
            "reminders": {"useDefault": True},
        }
        try:
            event = (
                service.events()
                .insert(
                    calendarId=self._settings.google_calendar_id,
                    body=body,
                    sendUpdates="all",  # this is what actually emails the owner
                )
                .execute()
            )
        except Exception as exc:  # noqa: BLE001 - any SDK/API failure
            raise CalendarError(f"Google Calendar rejected the event: {exc}") from exc

        return CreatedEvent(event_id=event["id"], html_link=event.get("htmlLink"))

    async def create_invite(self, invite: CalendarInvite) -> CreatedEvent:
        # The Google SDK is blocking; keep the event loop free.
        return await asyncio.to_thread(self._create_sync, invite)
