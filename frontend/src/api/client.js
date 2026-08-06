import axios from "axios";

// Vite proxies /api -> http://localhost:8000 (see vite.config.js), so the
// frontend never needs to know the backend's host in development.
const client = axios.create({ baseURL: "/api" });

/**
 * Surface what actually went wrong.
 *
 * The API returns the real upstream error in `detail.error` — a GitHub
 * 403, a Mongo timeout — and this used to drop it, showing only the
 * generic message. That sent people hunting through server logs for
 * something the response already contained.
 */
function unwrapError(error) {
  const detail = error?.response?.data?.detail;
  if (typeof detail === "string") return new Error(detail);
  if (detail?.message || detail?.error) {
    const err = new Error(detail.message || detail.error);
    err.reasons = detail.reasons || [];
    err.upstream = detail.error || null;
    return err;
  }
  if (error?.message) return error;
  return new Error("Request failed for an unknown reason.");
}

export async function getReadiness() {
  const { data } = await client.get("/readiness");
  return data;
}

export async function listMeetings() {
  const { data } = await client.get("/meetings");
  return data;
}

export async function deleteMeeting(meetingId) {
  try {
    const { data } = await client.delete(`/meetings/${meetingId}`);
    return data;
  } catch (error) {
    throw unwrapError(error);
  }
}

export async function getReport(meetingId) {
  const { data } = await client.get(`/meetings/${meetingId}/report`);
  return data;
}

/** Direct link: the browser downloads/renders markdown itself. */
export function reportMarkdownUrl(meetingId) {
  return `/api/meetings/${meetingId}/report.md`;
}

export async function getActionsTaken(meetingId) {
  const { data } = await client.get(`/meetings/${meetingId}/actions`);
  return data;
}

export async function getTranscript(meetingId) {
  const { data } = await client.get(`/meetings/${meetingId}/transcript`);
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

export async function approveCandidate(candidateId, reviewer, effects = null, payload = null) {
  try {
    const body = { reviewer };
    if (effects?.length) body.effects = effects;
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

/**
 * Edit the item itself. Passing `classification` is the reviewer
 * overruling the model's reading — recorded as a human override, and it
 * lifts the confidence score because someone who was in the room knows
 * better than the extractor did.
 */
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

export async function getAgents() {
  const { data } = await client.get("/system/agents");
  return data;
}

export async function getTools() {
  const { data } = await client.get("/system/tools");
  return data;
}

export async function getAgentRun(meetingId) {
  const { data } = await client.get(`/system/meetings/${meetingId}/agent-run`);
  return data;
}

export async function searchMemory(query, excludeMeetingId = null) {
  const params = { q: query };
  if (excludeMeetingId) params.exclude_meeting_id = excludeMeetingId;
  const { data } = await client.get("/system/memory/search", { params });
  return data;
}

/**
 * Opens the live-meeting websocket. Vite proxies /api -> backend, but a
 * websocket needs an absolute ws:// URL, so it is built from the current
 * page origin rather than hardcoded.
 */
export function openLiveSocket() {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return new WebSocket(`${proto}//${window.location.host}/api/live`);
}
