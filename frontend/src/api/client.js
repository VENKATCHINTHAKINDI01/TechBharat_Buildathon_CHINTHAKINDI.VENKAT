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
