import axios from "axios";

// Vite proxies /api -> http://localhost:8000 (see vite.config.js), so the
// frontend never needs to know the backend's host in development.
const client = axios.create({ baseURL: "/api" });

function unwrapError(error) {
  const detail = error?.response?.data?.detail;
  if (typeof detail === "string") return new Error(detail);
  if (detail?.message) {
    const err = new Error(detail.message);
    err.reasons = detail.reasons || [];
    return err;
  }
  return error;
}

export async function getReadiness() {
  const { data } = await client.get("/readiness");
  return data;
}

export async function listMeetings() {
  const { data } = await client.get("/meetings");
  return data;
}

export async function uploadMeeting({ file, title, meetingDate, participants }) {
  const form = new FormData();
  form.append("file", file);
  form.append("title", title);
  form.append("meeting_date", meetingDate);
  form.append("participants", participants);
  try {
    const { data } = await client.post("/meetings", form);
    return data;
  } catch (error) {
    throw unwrapError(error);
  }
}

export async function getMeeting(meetingId) {
  const { data } = await client.get(`/meetings/${meetingId}`);
  return data;
}

export async function approveCandidate(candidateId, reviewer, payload = null) {
  try {
    const body = { reviewer };
    if (payload) body.payload = payload;
    const { data } = await client.post(`/review/candidates/${candidateId}/approve`, body);
    return data;
  } catch (error) {
    throw unwrapError(error);
  }
}

export async function rejectCandidate(candidateId, reviewer, reason) {
  const { data } = await client.post(`/review/candidates/${candidateId}/reject`, {
    reviewer,
    reason,
  });
  return data;
}

export async function editCandidate(candidateId, reviewer, changes) {
  try {
    const { data } = await client.patch(`/review/candidates/${candidateId}`, {
      reviewer,
      ...changes,
    });
    return data;
  } catch (error) {
    throw unwrapError(error);
  }
}

export async function getAuditLog(meetingId) {
  const { data } = await client.get(`/review/meetings/${meetingId}/audit`);
  return data;
}
