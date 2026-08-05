"""
Computes WHEN a follow-up reminder should fire for an approved item --
pure logic, no sending. This is intentionally scoped narrow: it decides
a send_at time, not the delivery mechanism (that's reminder_send_tool).

Honest scope note: there is no background scheduler wired up yet
(no APScheduler/cron running). This tool computes and stores intent;
actually firing reminders on schedule is a Phase 5+ addition. The
CALENDAR INVITE created at approval time (calendar_tool) is the real,
working notification for the demo -- this reminder layer is the
"nudge before the deadline" stretch behavior on top of that.
"""
from datetime import datetime, timedelta


def compute_reminder_time(due_date: datetime | None) -> datetime | None:
    if due_date is None:
        return None
    reminder_time = due_date - timedelta(hours=24)
    now = datetime.utcnow()
    return reminder_time if reminder_time > now else now