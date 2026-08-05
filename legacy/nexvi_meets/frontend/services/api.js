import axios from "axios";

const client = axios.create({ baseURL: "/api" });

export async function checkHealth() {
  const { data } = await axios.get("/health"); // proxied to backend :8000
  return data;
}

export async function uploadMeeting(file, title, meetingDate, calendarEventId = null, manualAttendees = null) {
  const form = new FormData();
  form.append("file", file);
  form.append("title", title);
  form.append("meeting_date", meetingDate);
  if (calendarEventId) form.append("calendar_event_id", calendarEventId);
  if (manualAttendees) form.append("manual_attendees", manualAttendees);
  const { data } = await axios.post("/meetings/upload", form, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data;
}

export async function getMeetingForReview(meetingId) {
  const { data } = await axios.get(`/review/meetings/${meetingId}`);
  return data;
}

export async function approveActionItem(dedupeHash, approvedBy = "demo_reviewer") {
  const { data } = await axios.post(`/review/action-items/${dedupeHash}/approve`, {
    approved_by: approvedBy,
  });
  return data;
}

export async function rejectActionItem(dedupeHash, approvedBy = "demo_reviewer", reason = null) {
  const { data } = await axios.post(`/review/action-items/${dedupeHash}/reject`, {
    approved_by: approvedBy,
    reason,
  });
  return data;
}

export async function editActionItem(dedupeHash, changes, approvedBy = "demo_reviewer") {
  const { data } = await axios.patch(`/review/action-items/${dedupeHash}`, {
    approved_by: approvedBy,
    ...changes,
  });
  return data;
}

export async function getAuditLog(meetingId) {
  const { data } = await axios.get(`/review/meetings/${meetingId}/audit-log`);
  return data;
}

export default client;