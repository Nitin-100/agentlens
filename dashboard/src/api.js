const API_BASE = '/api/v1';

async function fetchAPI(endpoint, options = {}) {
  const res = await fetch(`${API_BASE}${endpoint}`, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  });
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

export async function getSessions(limit = 50, offset = 0, agent = null, user = null) {
  const params = new URLSearchParams({ limit, offset });
  if (agent) params.append('agent', agent);
  if (user) params.append('user', user);
  return fetchAPI(`/sessions?${params}`);
}

export async function getSession(id) {
  return fetchAPI(`/sessions/${id}`);
}

export async function getEvents(limit = 100, eventType = null) {
  const params = new URLSearchParams({ limit });
  if (eventType) params.append('event_type', eventType);
  return fetchAPI(`/events?${params}`);
}

export async function getAnalytics(hours = 24) {
  return fetchAPI(`/analytics?hours=${hours}`);
}

export async function getLiveEvents() {
  return fetchAPI('/live');
}

// ─── Alerts API ─────────────────────────────────────────────

export async function getAlerts() {
  return fetchAPI('/alerts');
}

export async function createAlert(rule) {
  return fetchAPI('/alerts', {
    method: 'POST',
    body: JSON.stringify(rule),
  });
}

export async function deleteAlert(ruleId) {
  return fetchAPI(`/alerts/${ruleId}`, { method: 'DELETE' });
}

// ─── Admin API ──────────────────────────────────────────────

export async function getAdminStats() {
  return fetchAPI('/admin/stats');
}

export async function cleanupData(days = 30) {
  return fetchAPI(`/admin/cleanup?days=${days}`, { method: 'POST' });
}

export async function getHealth() {
  return fetch('/api/health').then(r => r.json());
}

// ─── WebSocket ──────────────────────────────────────────────

export function connectLiveWS(project = 'default', onEvent, onAlert) {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const ws = new WebSocket(`${protocol}//${window.location.host}/ws/live?project=${project}`);

  ws.onopen = () => console.log('[AgentLens] WS connected');
  ws.onmessage = (msg) => {
    try {
      const data = JSON.parse(msg.data);
      if (data.type === 'event' && onEvent) onEvent(data.data);
      if (data.type === 'alert' && onAlert) onAlert(data.data);
    } catch (e) {}
  };
  ws.onerror = (e) => console.warn('[AgentLens] WS error', e);
  ws.onclose = () => {
    console.log('[AgentLens] WS disconnected, reconnecting in 3s...');
    setTimeout(() => connectLiveWS(project, onEvent, onAlert), 3000);
  };

  // Keep alive
  const pingInterval = setInterval(() => {
    if (ws.readyState === WebSocket.OPEN) ws.send('ping');
  }, 30000);

  return {
    close: () => { clearInterval(pingInterval); ws.close(); },
    ws,
  };
}

// ─── Trace Tree (Nested Spans) ──────────────────────────────

export async function getTraceTree(traceId) {
  return fetchAPI(`/traces/${traceId}`);
}

// ─── Prompt Diff / Replay ───────────────────────────────────

export async function getEventDetail(eventId) {
  return fetchAPI(`/events/${eventId}/detail`);
}

export async function diffEvents(eventId, otherEventId) {
  return fetchAPI(`/events/${eventId}/diff/${otherEventId}`);
}

// ─── Cost Anomaly Detection ─────────────────────────────────

export async function getAnomalies(limit = 50) {
  return fetchAPI(`/anomalies?limit=${limit}`);
}

export async function getCostTrends(days = 30) {
  return fetchAPI(`/anomalies/trends?days=${days}`);
}

export async function acknowledgeAnomaly(anomalyId) {
  return fetchAPI(`/anomalies/${anomalyId}/acknowledge`, { method: 'POST' });
}

export async function triggerAnomalyDetection() {
  return fetchAPI('/anomalies/detect', { method: 'POST' });
}

// ─── Demo Data ──────────────────────────────────────────────

export async function loadDemoData() {
  return fetchAPI('/demo/load', { method: 'POST' });
}

// ─── Session Graph (DAG) ────────────────────────────────────

export async function getSessionGraph(sessionId) {
  return fetchAPI(`/sessions/${sessionId}/graph`);
}

