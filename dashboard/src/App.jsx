import React, { useState, useEffect, useCallback, useRef, Component } from 'react';
import {
  getSessions, getSession, getEvents, getAnalytics, getLiveEvents,
  getAlerts, createAlert, deleteAlert, getAdminStats, cleanupData,
  getHealth, connectLiveWS,
  getTraceTree, getEventDetail, diffEvents, getAnomalies, getCostTrends,
  acknowledgeAnomaly, triggerAnomalyDetection, loadDemoData, getSessionGraph,
} from './api';

// ─── Error Boundary ─────────────────────────────────────────
class ErrorBoundary extends Component {
  state = { hasError: false, error: null };

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, info) {
    console.error('[AgentLens] UI Crash:', error, info);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div style={{ padding: 40, textAlign: 'center', color: '#ef4444' }}>
          <h2>Dashboard Crashed</h2>
          <pre style={{ color: '#94a3b8', fontSize: 13, marginTop: 12 }}>
            {this.state.error?.message}
          </pre>
          <button
            onClick={() => { this.setState({ hasError: false }); window.location.reload(); }}
            style={{ marginTop: 20, padding: '8px 24px', background: '#111827', color: '#fff', border: 'none', borderRadius: 6, cursor: 'pointer' }}
          >
            Reload Dashboard
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

// ─── Styles ─────────────────────────────────────────────────
const THEME = {
  bg: '#ffffff', surface: '#f8f9fa', surfaceHover: '#f1f3f5',
  border: '#e5e7eb', text: '#111827', textMuted: '#6b7280',
  primary: '#111827', success: '#16a34a', warning: '#d97706',
  error: '#dc2626', info: '#0891b2',
};

const css = `
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: ${THEME.bg}; color: ${THEME.text}; font-family: 'Inter', -apple-system, sans-serif; }
  a { color: ${THEME.primary}; text-decoration: none; }
  .container { display: flex; min-height: 100vh; }
  .sidebar { width: 220px; background: ${THEME.surface}; border-right: 1px solid ${THEME.border}; padding: 20px 0; flex-shrink: 0; display: flex; flex-direction: column; }
  .sidebar-brand { padding: 0 20px 20px; font-size: 18px; font-weight: 700; color: ${THEME.primary}; border-bottom: 1px solid ${THEME.border}; display: flex; align-items: center; gap: 8px; }
  .sidebar-nav { flex: 1; padding: 12px 0; }
  .nav-item { padding: 10px 20px; cursor: pointer; color: ${THEME.textMuted}; font-size: 14px; display: flex; align-items: center; gap: 10px; transition: all 0.15s; border-left: 3px solid transparent; }
  .nav-item:hover { background: ${THEME.surfaceHover}; color: ${THEME.text}; }
  .nav-item.active { color: ${THEME.primary}; border-left-color: ${THEME.primary}; background: rgba(17,24,39,0.06); }
  .sidebar-footer { padding: 12px 20px; border-top: 1px solid ${THEME.border}; font-size: 11px; color: ${THEME.textMuted}; }
  .health-dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; margin-right: 6px; }
  .main { flex: 1; padding: 28px 32px; overflow-y: auto; max-height: 100vh; }
  .page-title { font-size: 22px; font-weight: 700; margin-bottom: 6px; }
  .page-subtitle { color: ${THEME.textMuted}; font-size: 13px; margin-bottom: 24px; }
  .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 14px; margin-bottom: 24px; }
  .stat-card { background: ${THEME.surface}; border: 1px solid ${THEME.border}; border-radius: 10px; padding: 18px; }
  .stat-label { font-size: 12px; color: ${THEME.textMuted}; text-transform: uppercase; letter-spacing: 0.5px; }
  .stat-value { font-size: 26px; font-weight: 700; margin-top: 4px; }
  .stat-sub { font-size: 11px; color: ${THEME.textMuted}; margin-top: 2px; }
  .card { background: ${THEME.surface}; border: 1px solid ${THEME.border}; border-radius: 10px; padding: 20px; margin-bottom: 18px; }
  .card-title { font-size: 15px; font-weight: 600; margin-bottom: 14px; display: flex; justify-content: space-between; align-items: center; }
  table { width: 100%; border-collapse: collapse; }
  th { text-align: left; padding: 10px 14px; font-size: 11px; color: ${THEME.textMuted}; text-transform: uppercase; border-bottom: 1px solid ${THEME.border}; }
  td { padding: 10px 14px; font-size: 13px; border-bottom: 1px solid ${THEME.border}; }
  tr:hover td { background: rgba(0,0,0,0.02); }
  .badge { padding: 3px 10px; border-radius: 12px; font-size: 11px; font-weight: 600; display: inline-block; }
  .badge-success { background: rgba(22,163,74,0.1); color: ${THEME.success}; }
  .badge-error { background: rgba(220,38,38,0.1); color: ${THEME.error}; }
  .badge-warning { background: rgba(217,119,6,0.1); color: ${THEME.warning}; }
  .badge-info { background: rgba(8,145,178,0.1); color: ${THEME.info}; }
  .badge-default { background: rgba(107,114,128,0.1); color: ${THEME.textMuted}; }
  .btn { padding: 8px 18px; border: none; border-radius: 6px; font-size: 13px; cursor: pointer; font-weight: 500; transition: all 0.15s; }
  .btn-primary { background: ${THEME.primary}; color: #fff; }
  .btn-primary:hover { background: #374151; }
  .btn-danger { background: ${THEME.error}; color: #fff; }
  .btn-sm { padding: 4px 12px; font-size: 12px; }
  .btn-ghost { background: transparent; color: ${THEME.textMuted}; border: 1px solid ${THEME.border}; }
  .btn-ghost:hover { color: ${THEME.text}; border-color: ${THEME.textMuted}; }
  .timeline { position: relative; padding-left: 28px; }
  .timeline::before { content: ''; position: absolute; left: 10px; top: 0; bottom: 0; width: 2px; background: ${THEME.border}; }
  .timeline-item { position: relative; margin-bottom: 16px; }
  .timeline-dot { position: absolute; left: -24px; top: 4px; width: 14px; height: 14px; border-radius: 50%; border: 2px solid ${THEME.bg}; }
  .timeline-content { background: ${THEME.bg}; border: 1px solid ${THEME.border}; border-radius: 8px; padding: 12px 16px; }
  .timeline-time { font-size: 11px; color: ${THEME.textMuted}; }
  .timeline-title { font-size: 13px; font-weight: 600; margin: 2px 0; }
  .timeline-detail { font-size: 12px; color: ${THEME.textMuted}; }
  .input { background: ${THEME.bg}; border: 1px solid ${THEME.border}; color: ${THEME.text}; padding: 8px 14px; border-radius: 6px; font-size: 13px; outline: none; }
  .input:focus { border-color: ${THEME.primary}; }
  select.input { cursor: pointer; }
  .flex { display: flex; } .items-center { align-items: center; } .gap-2 { gap: 8px; } .gap-3 { gap: 12px; }
  .justify-between { justify-content: space-between; } .flex-wrap { flex-wrap: wrap; }
  .mb-4 { margin-bottom: 16px; } .mt-2 { margin-top: 8px; } .ml-auto { margin-left: auto; }
  .text-sm { font-size: 13px; } .text-xs { font-size: 11px; } .text-muted { color: ${THEME.textMuted}; }
  .toast-container { position: fixed; top: 20px; right: 20px; z-index: 9999; display: flex; flex-direction: column; gap: 8px; }
  .toast { padding: 12px 20px; border-radius: 8px; font-size: 13px; animation: slideIn 0.3s ease; box-shadow: 0 4px 20px rgba(0,0,0,0.15); }
  .toast-error { background: ${THEME.error}; color: #fff; }
  .toast-success { background: ${THEME.success}; color: #fff; }
  .toast-warning { background: ${THEME.warning}; color: #000; }
  @keyframes slideIn { from { transform: translateX(100%); opacity: 0; } to { transform: translateX(0); opacity: 1; } }
  .empty { text-align: center; padding: 40px; color: ${THEME.textMuted}; }
  .code-block { background: ${THEME.bg}; border: 1px solid ${THEME.border}; border-radius: 6px; padding: 16px; font-family: 'JetBrains Mono', monospace; font-size: 13px; overflow-x: auto; white-space: pre; color: ${THEME.textMuted}; }
  .alert-row { display: flex; align-items: center; gap: 12px; padding: 12px 0; border-bottom: 1px solid ${THEME.border}; }
  .alert-row:last-child { border-bottom: none; }
  .error-bar { height: 6px; border-radius: 3px; background: ${THEME.border}; overflow: hidden; flex: 1; }
  .error-bar-fill { height: 100%; border-radius: 3px; transition: width 0.5s; }
  .tabs { display: flex; gap: 0; border-bottom: 1px solid ${THEME.border}; margin-bottom: 20px; }
  .tab { padding: 10px 20px; cursor: pointer; font-size: 13px; color: ${THEME.textMuted}; border-bottom: 2px solid transparent; transition: all 0.15s; }
  .tab:hover { color: ${THEME.text}; }
  .tab.active { color: ${THEME.primary}; border-bottom-color: ${THEME.primary}; }

  /* ─── Trace Tree ─── */
  .trace-tree { font-size: 13px; font-family: 'Inter', -apple-system, sans-serif; }
  .trace-node { margin-bottom: 1px; }
  .trace-node-header { display: flex; align-items: center; gap: 6px; padding: 7px 10px; border-radius: 6px; cursor: pointer; transition: background 0.15s; border-left: 3px solid transparent; }
  .trace-node-header:hover { background: ${THEME.surfaceHover}; border-left-color: ${THEME.primary}; }
  .trace-toggle { width: 20px; font-size: 10px; color: ${THEME.textMuted}; flex-shrink: 0; text-align: center; user-select: none; }
  .trace-children { margin-left: 20px; border-left: 2px solid ${THEME.border}; padding-left: 10px; }
  .waterfall-bar { height: 20px; border-radius: 4px; position: relative; min-width: 6px; display: flex; align-items: center; padding: 0 6px; font-size: 10px; font-weight: 600; color: #fff; white-space: nowrap; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.12); }

  /* ─── Prompt Diff ─── */
  .modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.5); z-index: 1000; display: flex; align-items: center; justify-content: center; }
  .modal { background: ${THEME.bg}; border-radius: 12px; max-width: 900px; width: 95vw; max-height: 85vh; overflow-y: auto; box-shadow: 0 20px 60px rgba(0,0,0,0.2); }
  .modal-header { padding: 18px 24px; border-bottom: 1px solid ${THEME.border}; display: flex; justify-content: space-between; align-items: center; }
  .modal-body { padding: 20px 24px; }
  .diff-line { font-family: 'JetBrains Mono', monospace; font-size: 12px; padding: 2px 8px; margin: 0; white-space: pre-wrap; word-break: break-word; }
  .diff-add { background: rgba(22,163,74,0.1); color: ${THEME.success}; }
  .diff-remove { background: rgba(220,38,38,0.1); color: ${THEME.error}; }
  .diff-same { color: ${THEME.textMuted}; }
  .side-by-side { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }

  /* ─── Agent Graph ─── */
  .graph-container { position: relative; background: ${THEME.surface}; border: 1px solid ${THEME.border}; border-radius: 10px; min-height: 400px; overflow: auto; }
  .graph-node { position: absolute; background: ${THEME.bg}; border: 2px solid ${THEME.border}; border-radius: 8px; padding: 10px 14px; font-size: 12px; cursor: pointer; min-width: 120px; text-align: center; transition: box-shadow 0.2s; z-index: 2; }
  .graph-node:hover { box-shadow: 0 4px 12px rgba(0,0,0,0.1); }
  .graph-node.success { border-color: ${THEME.success}; }
  .graph-node.error { border-color: ${THEME.error}; }
  .graph-node.running { border-color: ${THEME.warning}; }

  /* ─── Anomaly ─── */
  .anomaly-card { background: rgba(220,38,38,0.04); border: 1px solid rgba(220,38,38,0.2); border-radius: 10px; padding: 16px; margin-bottom: 10px; }
  .anomaly-card.acknowledged { opacity: 0.6; }
  .spike-badge { background: ${THEME.error}; color: #fff; padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: 700; }
`;

// ─── Helpers ────────────────────────────────────────────────
const fmt = (n) => n >= 1000000 ? (n / 1000000).toFixed(1) + 'M' : n >= 1000 ? (n / 1000).toFixed(1) + 'K' : String(n ?? 0);
const fmtCost = (c) => '$' + (c ?? 0).toFixed(4);
const fmtTime = (t) => {
  if (!t) return '—';
  const d = new Date(typeof t === 'number' ? t * 1000 : t);
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
};
const fmtDate = (t) => {
  if (!t) return '—';
  const d = new Date(typeof t === 'number' ? t * 1000 : t);
  return d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
};
const fmtDuration = (s) => {
  if (!s && s !== 0) return '—';
  if (s < 1) return (s * 1000).toFixed(0) + 'ms';
  if (s < 60) return s.toFixed(1) + 's';
  return (s / 60).toFixed(1) + 'm';
};

const EVENT_COLORS = {
  llm_call: '#111827', 'llm.response': '#111827', tool_call: THEME.success, 'tool.call': THEME.success,
  'tool.error': THEME.error, step_start: THEME.info, step_end: THEME.info, 'agent.step': THEME.info,
  error: THEME.error, agent_start: '#6b7280', agent_end: '#6b7280',
  'session.start': '#0891b2', 'session.end': '#0891b2', session_start: '#0891b2', session_end: '#0891b2',
  retry: THEME.warning, fallback: THEME.warning, custom: THEME.textMuted,
};

const eventBadge = (type) => {
  if (!type) return 'default';
  if (type.includes('llm')) return 'info';
  if (type.includes('tool') && !type.includes('error')) return 'success';
  if (type.includes('error')) return 'error';
  if (type.includes('retry') || type.includes('fallback')) return 'warning';
  if (type.includes('step')) return 'info';
  return 'default';
};

// ─── Toast Hook ─────────────────────────────────────────────
function useToast() {
  const [toasts, setToasts] = useState([]);
  const add = useCallback((message, type = 'success') => {
    const id = Date.now();
    setToasts(t => [...t, { id, message, type }]);
    setTimeout(() => setToasts(t => t.filter(x => x.id !== id)), 4000);
  }, []);
  const ToastContainer = () => (
    <div className="toast-container">
      {toasts.map(t => <div key={t.id} className={`toast toast-${t.type}`}>{t.message}</div>)}
    </div>
  );
  return { toast: add, ToastContainer };
}

// ─── Pages ──────────────────────────────────────────────────

// ─── Reusable Components ────────────────────────────────────

// Trace Tree Node (recursive)
function TraceNode({ event, traceStart, traceDuration, depth = 0, onEventClick }) {
  const [expanded, setExpanded] = useState(depth < 2);
  const hasChildren = event.children && event.children.length > 0;

  const eventStart = (event.timestamp || 0) - traceStart;
  const eventDuration = event.duration_ms || event.latency_ms || 0;
  const leftPct = traceDuration > 0 ? (eventStart * 1000 / traceDuration) * 100 : 0;
  const widthPct = traceDuration > 0 ? Math.max((eventDuration / traceDuration) * 100, 1.5) : 5;

  const type = event.event_type || '';
  const isError = event.success === false || event.success === 0 || type.includes('error');

  const barColor = isError ? THEME.error
    : type.includes('session') ? '#0891b2'
    : type.includes('step') ? '#6366f1'
    : type.includes('llm') ? '#111827'
    : type.includes('tool') ? THEME.success
    : THEME.textMuted;

  // Descriptive label
  const label = type.includes('session.start') ? (event.agent_name || 'session')
    : type.includes('session.end') ? (event.success ? 'completed' : 'failed')
    : type.includes('agent.step') ? `step [${event.step_number || '?'}] ${(event.decision || event.thought || '').slice(0, 45)}`
    : type.includes('llm') ? `${event.model || 'LLM'}${event.cost_usd > 0 ? ', ' + fmtCost(event.cost_usd) : ''}`
    : type.includes('tool') ? (event.tool_name || 'tool')
    : event.tool_name || event.model || type.split('.').pop() || 'span';

  const durationLabel = eventDuration >= 1000 ? (eventDuration / 1000).toFixed(1) + 's'
    : eventDuration > 0 ? eventDuration.toFixed(0) + 'ms' : '';

  return (
    <div className="trace-node">
      <div className="trace-node-header" onClick={() => onEventClick?.(event)}
        style={{ background: isError ? 'rgba(220,38,38,0.04)' : 'transparent' }}>
        <span className="trace-toggle" onClick={e => { e.stopPropagation(); setExpanded(!expanded); }}>
          {hasChildren ? (expanded ? '▼' : '▶') : '·'}
        </span>
        <span className={`badge badge-${eventBadge(type)}`} style={{ fontSize: 10 }}>{type}</span>
        <span style={{ fontWeight: 600, fontSize: 12, maxWidth: 300, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {label}
        </span>
        {event.total_tokens > 0 && <span className="text-xs text-muted">{event.total_tokens} tok</span>}
        {durationLabel && <span className="text-xs text-muted" style={{ fontFamily: 'monospace' }}>{durationLabel}</span>}
        {isError && <span className="badge badge-error" style={{ fontSize: 9 }}>ERR</span>}
        <div style={{ flex: 1, marginLeft: 8, height: 20, position: 'relative', background: 'rgba(0,0,0,0.03)', borderRadius: 3 }}>
          <div className="waterfall-bar" style={{
            background: barColor, position: 'absolute',
            left: `${Math.min(Math.max(leftPct, 0), 95)}%`,
            width: `${Math.min(Math.max(widthPct, 1.5), 100 - Math.max(leftPct, 0))}%`,
            opacity: isError ? 1 : 0.75,
          }}>
            {widthPct > 8 ? durationLabel : ''}
          </div>
        </div>
      </div>
      {expanded && hasChildren && (
        <div className="trace-children">
          {event.children.map((child, i) => (
            <TraceNode key={child.id || i} event={child} traceStart={traceStart}
              traceDuration={traceDuration} depth={depth + 1} onEventClick={onEventClick} />
          ))}
        </div>
      )}
    </div>
  );
}

// Prompt Diff Modal
function PromptDiffModal({ event, onClose }) {
  const [similar, setSimilar] = useState([]);
  const [diffData, setDiffData] = useState(null);
  const [selectedId, setSelectedId] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!event) return;
    setLoading(true);
    getEventDetail(event.id || event.event_id)
      .then(r => { setSimilar(r.similar_prompts || []); setLoading(false); })
      .catch(() => setLoading(false));
  }, [event]);

  const loadDiff = async (otherId) => {
    setSelectedId(otherId);
    try {
      const d = await diffEvents(event.id || event.event_id, otherId);
      setDiffData(d);
    } catch (e) { console.error(e); }
  };

  if (!event) return null;

  const prompt = event.prompt || event.data?.prompt || '';
  const completion = event.completion || event.data?.completion || '';

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <div>
            <h3 style={{ margin: 0, fontSize: 16 }}>Prompt Replay & Diff</h3>
            <span className="text-xs text-muted">{event.model || 'LLM Call'} — {fmtTime(event.timestamp)}</span>
          </div>
          <button className="btn btn-ghost btn-sm" onClick={onClose}>✕</button>
        </div>
        <div className="modal-body">
          {/* Side-by-side: prompt + completion */}
          <div className="side-by-side" style={{ marginBottom: 20 }}>
            <div>
              <div style={{ fontWeight: 600, fontSize: 12, marginBottom: 6 }}>Prompt</div>
              <pre className="code-block" style={{ maxHeight: 200, overflow: 'auto', fontSize: 11, whiteSpace: 'pre-wrap' }}>
                {prompt || '(no prompt captured)'}
              </pre>
            </div>
            <div>
              <div style={{ fontWeight: 600, fontSize: 12, marginBottom: 6 }}>Completion</div>
              <pre className="code-block" style={{ maxHeight: 200, overflow: 'auto', fontSize: 11, whiteSpace: 'pre-wrap' }}>
                {completion || '(no completion captured)'}
              </pre>
            </div>
          </div>

          {/* Stats */}
          <div className="flex gap-3" style={{ marginBottom: 16 }}>
            {event.total_tokens > 0 && <span className="badge badge-info">🔤 {event.total_tokens} tokens</span>}
            {event.cost_usd > 0 && <span className="badge badge-warning">💰 {fmtCost(event.cost_usd)}</span>}
            {event.latency_ms > 0 && <span className="badge badge-default">⏱ {event.latency_ms.toFixed(0)}ms</span>}
            {event.success === true && <span className="badge badge-success">✓ Success</span>}
            {event.success === false && <span className="badge badge-error">✗ Failed</span>}
          </div>

          {/* Similar prompts for diffing */}
          {loading ? (
            <div className="text-sm text-muted">Finding similar prompts...</div>
          ) : similar.length > 0 ? (
            <>
              <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 8 }}>Similar Prompts</div>
              <div style={{ maxHeight: 150, overflowY: 'auto', marginBottom: 16 }}>
                {similar.map(s => (
                  <div key={s.event_id} onClick={() => loadDiff(s.event_id)}
                    style={{ padding: '6px 10px', borderRadius: 6, cursor: 'pointer', marginBottom: 4,
                      background: selectedId === s.event_id ? 'rgba(17,24,39,0.08)' : 'transparent',
                      border: `1px solid ${selectedId === s.event_id ? THEME.primary : THEME.border}` }}>
                    <div className="flex justify-between items-center">
                      <span className="text-xs">{s.similarity}% similar — {s.model}</span>
                      <span className="text-xs text-muted">{fmtTime(s.timestamp)}</span>
                    </div>
                  </div>
                ))}
              </div>
            </>
          ) : null}

          {/* Diff view */}
          {diffData && (
            <div>
              <div className="flex items-center gap-2" style={{ marginBottom: 8 }}>
                <span style={{ fontWeight: 600, fontSize: 13 }}>Prompt Diff</span>
                <span className="badge badge-info">{diffData.prompt_similarity}% match</span>
              </div>
              <div style={{ background: THEME.surface, borderRadius: 8, padding: 8, maxHeight: 250, overflowY: 'auto', border: `1px solid ${THEME.border}` }}>
                {diffData.prompt_diff?.map((line, i) => (
                  <div key={i} className={`diff-line diff-${line.type}`}>
                    {line.type === 'added' ? '+ ' : line.type === 'removed' ? '- ' : '  '}{line.text}
                  </div>
                ))}
              </div>
              {diffData.completion_diff?.length > 0 && (
                <>
                  <div className="flex items-center gap-2" style={{ margin: '12px 0 8px' }}>
                    <span style={{ fontWeight: 600, fontSize: 13 }}>Completion Diff</span>
                    <span className="badge badge-info">{diffData.completion_similarity}% match</span>
                  </div>
                  <div style={{ background: THEME.surface, borderRadius: 8, padding: 8, maxHeight: 200, overflowY: 'auto', border: `1px solid ${THEME.border}` }}>
                    {diffData.completion_diff.map((line, i) => (
                      <div key={i} className={`diff-line diff-${line.type}`}>
                        {line.type === 'added' ? '+ ' : line.type === 'removed' ? '- ' : '  '}{line.text}
                      </div>
                    ))}
                  </div>
                </>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// Agent Graph (DAG Visualization)
function AgentGraphView({ sessionId }) {
  const [graph, setGraph] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    getSessionGraph(sessionId)
      .then(setGraph)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [sessionId]);

  if (loading) return <div className="empty">Loading graph...</div>;
  if (!graph || !graph.nodes?.length) return <div className="empty">No graph data for this session</div>;

  /*
   * Layout strategy:
   *   Row 0 (top):   spine nodes — session.start → step1 → step2 → session.end
   *   Row 1 (below): leaf nodes — llm / tool children positioned under their parent step
   *
   *   Edges: horizontal flow arrows along spine, vertical drop arrows to leaves.
   */

  const NODE_W = 160, NODE_H = 56, SPINE_GAP = 200, LEAF_GAP = 90, PAD = 40;
  const SPINE_Y = PAD;
  const LEAF_Y = PAD + NODE_H + 60;

  const nodeMap = {};
  graph.nodes.forEach(n => { nodeMap[n.id] = n; });

  // Separate spine vs leaf
  const spineNodes = graph.nodes.filter(n => n.role === 'spine');
  const leafNodes = graph.nodes.filter(n => n.role === 'leaf');

  // Build parent→leaf mapping
  const leafByParent = {};
  graph.edges.forEach(e => {
    if (e.type === 'child') {
      leafByParent[e.from] = leafByParent[e.from] || [];
      leafByParent[e.from].push(e.to);
    }
  });

  // Position spine nodes in a horizontal row
  const positions = {};
  spineNodes.forEach((node, idx) => {
    positions[node.id] = { x: PAD + idx * SPINE_GAP, y: SPINE_Y };
  });

  // Position leaf nodes below their parent spine node, spread horizontally
  spineNodes.forEach(sn => {
    const children = leafByParent[sn.id] || [];
    const parentX = positions[sn.id]?.x || 0;
    const totalChildWidth = children.length * LEAF_GAP;
    const startX = parentX + NODE_W / 2 - totalChildWidth / 2;
    children.forEach((cid, ci) => {
      positions[cid] = {
        x: startX + ci * LEAF_GAP,
        y: LEAF_Y,
      };
    });
  });

  const allX = Object.values(positions).map(p => p.x);
  const allY = Object.values(positions).map(p => p.y);
  const canvasW = Math.max(...allX) + NODE_W + PAD * 2;
  const canvasH = Math.max(...allY) + NODE_H + PAD * 2;

  // Build edge data with types for styling
  const flowEdges = graph.edges.filter(e => e.type === 'flow');
  const childEdges = graph.edges.filter(e => e.type === 'child');

  // Status-to-color
  const statusColor = (s) => s === 'error' ? THEME.error : s === 'running' ? THEME.warning : THEME.success;

  return (
    <div className="graph-container" style={{ width: '100%', minHeight: Math.max(canvasH, 250), position: 'relative', overflow: 'auto' }}>
      <svg style={{ position: 'absolute', top: 0, left: 0, width: canvasW, height: canvasH, zIndex: 1 }}>
        <defs>
          <marker id="arrow-flow" viewBox="0 0 10 10" refX="10" refY="5"
            markerWidth="7" markerHeight="7" orient="auto">
            <path d="M 0 1 L 10 5 L 0 9 z" fill="#374151" />
          </marker>
          <marker id="arrow-child" viewBox="0 0 10 10" refX="5" refY="10"
            markerWidth="7" markerHeight="7" orient="auto">
            <path d="M 0 1 L 10 5 L 0 9 z" fill="#9ca3af" />
          </marker>
        </defs>

        {/* Flow edges (horizontal along spine) */}
        {flowEdges.map((edge, i) => {
          const from = positions[edge.from];
          const to = positions[edge.to];
          if (!from || !to) return null;
          const x1 = from.x + NODE_W;
          const y1 = from.y + NODE_H / 2;
          const x2 = to.x;
          const y2 = to.y + NODE_H / 2;
          return (
            <line key={'f' + i} x1={x1} y1={y1} x2={x2} y2={y2}
              stroke="#374151" strokeWidth={2.5} markerEnd="url(#arrow-flow)" />
          );
        })}

        {/* Child edges (vertical drop from spine to leaf) */}
        {childEdges.map((edge, i) => {
          const from = positions[edge.from];
          const to = positions[edge.to];
          if (!from || !to) return null;
          const x1 = from.x + NODE_W / 2;
          const y1 = from.y + NODE_H;
          const x2 = to.x + NODE_W / 2;
          const y2 = to.y;
          // Smooth vertical path
          const midY = y1 + (y2 - y1) * 0.5;
          const d = `M ${x1} ${y1} C ${x1} ${midY}, ${x2} ${midY}, ${x2} ${y2}`;
          return (
            <path key={'c' + i} d={d}
              fill="none" stroke="#d1d5db" strokeWidth={1.5} strokeDasharray="4 3"
              markerEnd="url(#arrow-child)" />
          );
        })}
      </svg>

      {/* Render nodes */}
      {graph.nodes.map(node => {
        const pos = positions[node.id];
        if (!pos) return null;
        const isSpine = node.role === 'spine';
        const borderColor = statusColor(node.status);
        return (
          <div key={node.id} style={{
            position: 'absolute', left: pos.x, top: pos.y,
            width: isSpine ? NODE_W : NODE_W * 0.75,
            background: '#fff',
            border: `2px solid ${borderColor}`,
            borderRadius: isSpine ? 10 : 8,
            padding: isSpine ? '10px 12px' : '6px 8px',
            fontSize: isSpine ? 12 : 11,
            textAlign: 'center',
            zIndex: 2,
            boxShadow: isSpine ? '0 2px 8px rgba(0,0,0,0.08)' : '0 1px 4px rgba(0,0,0,0.06)',
          }}>
            <div style={{ fontWeight: 700, marginBottom: 2, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
              {node.label}
            </div>
            <div style={{ fontSize: 10, color: THEME.textMuted }}>{node.type}</div>
            <div style={{ fontSize: 10, color: THEME.textMuted, marginTop: 2 }}>
              {node.duration_ms > 0 ? `${node.duration_ms.toFixed(0)}ms` : ''}
              {node.cost_usd > 0 ? ` · ${fmtCost(node.cost_usd)}` : ''}
              {node.tokens > 0 ? ` · ${node.tokens} tok` : ''}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// Overview
function OverviewPage({ onNavigate }) {
  const [data, setData] = useState(null);
  const [hours, setHours] = useState(24);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    getAnalytics(hours).then(setData).catch(console.error).finally(() => setLoading(false));
  }, [hours]);

  if (loading) return <div className="empty">Loading analytics...</div>;
  if (!data) return <div className="empty">No data yet. Run demo_agent.py to populate.</div>;

  const totalEvents = data.total_events || (data.llm_calls + data.tool_calls + data.errors) || 0;
  const totalErrors = data.total_errors || data.errors || 0;
  const errorRate = totalEvents ? (totalErrors / totalEvents * 100).toFixed(1) : '0.0';
  const avgLatencyMs = data.avg_latency_ms || data.avg_latency || 0;
  const avgLatency = avgLatencyMs ? fmtDuration(avgLatencyMs / 1000) : '—';

  return (
    <div>
      <div className="flex justify-between items-center mb-4">
        <div>
          <h1 className="page-title">Overview</h1>
          <p className="page-subtitle">Agent observability at a glance</p>
        </div>
        <select className="input" value={hours} onChange={e => setHours(+e.target.value)}>
          <option value={1}>Last 1h</option>
          <option value={6}>Last 6h</option>
          <option value={24}>Last 24h</option>
          <option value={168}>Last 7d</option>
        </select>
      </div>

      <div className="stats-grid">
        <div className="stat-card">
          <div className="stat-label">Sessions</div>
          <div className="stat-value">{fmt(data.total_sessions)}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Events</div>
          <div className="stat-value">{fmt(totalEvents)}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Total Cost</div>
          <div className="stat-value">{fmtCost(data.total_cost_usd || data.total_cost)}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Tokens</div>
          <div className="stat-value">{fmt(data.total_tokens)}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Error Rate</div>
          <div className="stat-value" style={{ color: parseFloat(errorRate) > 5 ? THEME.error : THEME.success }}>
            {errorRate}%
          </div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Avg Latency</div>
          <div className="stat-value">{avgLatency}</div>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 18 }}>
        <div className="card">
          <div className="card-title">Top Agents</div>
          {(data.agents || data.top_agents)?.length ? (
            <table>
              <thead><tr><th>Agent</th><th>Sessions</th><th>Errors</th></tr></thead>
              <tbody>
                {(data.agents || data.top_agents).map(a => (
                  <tr key={a.agent_name || a.name} style={{ cursor: 'pointer' }} onClick={() => onNavigate('sessions', { agent: a.agent_name || a.name })}>
                    <td style={{ color: '#111827', fontWeight: 600 }}>{a.agent_name || a.name}</td>
                    <td>{a.sessions}</td>
                    <td>{(a.errors || 0) > 0 ? <span style={{ color: THEME.error }}>{a.errors}</span> : '0'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : <div className="text-sm text-muted">No agents recorded yet</div>}
        </div>

        <div className="card">
          <div className="card-title">Models Used</div>
          {(data.top_models || data.models_used)?.length ? (
            <table>
              <thead><tr><th>Model</th><th>Calls</th><th>Tokens</th><th>Cost</th></tr></thead>
              <tbody>
                {(data.top_models || data.models_used).map(m => (
                  <tr key={m.model}>
                    <td style={{ fontFamily: 'monospace', fontSize: 12 }}>{m.model}</td>
                    <td>{m.count || m.calls}</td>
                    <td>{fmt(m.tokens)}</td>
                    <td>{fmtCost(m.cost)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : <div className="text-sm text-muted">No LLM calls yet</div>}
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 18 }}>
        <div className="card">
          <div className="card-title">Top Tools</div>
          {data.top_tools?.length ? (
            <table>
              <thead><tr><th>Tool</th><th>Calls</th><th>Errors</th><th>Avg Duration</th></tr></thead>
              <tbody>
                {data.top_tools.map(t => (
                  <tr key={t.tool_name || t.name}>
                    <td style={{ color: THEME.success, fontWeight: 600 }}>{t.tool_name || t.name}</td>
                    <td>{t.count || t.calls}</td>
                    <td>{(t.failures || t.errors || 0) > 0 ? <span style={{ color: THEME.error }}>{t.failures || t.errors}</span> : '0'}</td>
                    <td>{fmtDuration((t.avg_duration || 0) / 1000)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : <div className="text-sm text-muted">No tools recorded yet</div>}
        </div>

        <div className="card">
          <div className="card-title">
            Error Breakdown
            <span className="text-xs text-muted">{totalErrors} total</span>
          </div>
          {data.error_types?.length ? (
            data.error_types.map(e => (
              <div key={e.error_type || e.type} className="flex items-center gap-2" style={{ marginBottom: 8 }}>
                <span style={{ width: 140, fontSize: 12, fontFamily: 'monospace', color: THEME.error }}>{e.error_type || e.type}</span>
                <div className="error-bar">
                  <div className="error-bar-fill" style={{ width: `${(e.count / (totalErrors || 1) * 100)}%`, background: THEME.error }} />
                </div>
                <span className="text-xs" style={{ minWidth: 30 }}>{e.count}</span>
              </div>
            ))
          ) : <div className="text-sm text-muted">No errors — great!</div>}
        </div>
      </div>
    </div>
  );
}

// Sessions
function SessionsPage({ onNavigate, initialAgent }) {
  const [sessions, setSessions] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [agentFilter, setAgentFilter] = useState(initialAgent || '');
  const [userFilter, setUserFilter] = useState('');
  const limit = 25;

  useEffect(() => {
    getSessions(limit, page * limit, agentFilter || null, userFilter || null)
      .then(r => { setSessions(r.sessions || r); setTotal(r.total || 0); })
      .catch(console.error);
  }, [page, agentFilter, userFilter]);

  const totalPages = Math.ceil(total / limit) || 1;

  return (
    <div>
      <h1 className="page-title">Sessions</h1>
      <p className="page-subtitle">All agent execution sessions</p>

      <div className="flex items-center gap-3 mb-4">
        <input
          className="input" placeholder="Filter by agent..." value={agentFilter}
          onChange={e => { setAgentFilter(e.target.value); setPage(0); }}
          style={{ width: 180 }}
        />
        <input
          className="input" placeholder="Filter by user..." value={userFilter}
          onChange={e => { setUserFilter(e.target.value); setPage(0); }}
          style={{ width: 180 }}
        />
        <span className="text-xs text-muted">{total} sessions</span>
        <div className="ml-auto flex gap-2">
          <button className="btn btn-ghost btn-sm" disabled={page === 0} onClick={() => setPage(p => p - 1)}>← Prev</button>
          <span className="text-xs text-muted" style={{ lineHeight: '28px' }}>Page {page + 1} / {totalPages}</span>
          <button className="btn btn-ghost btn-sm" disabled={page >= totalPages - 1} onClick={() => setPage(p => p + 1)}>Next →</button>
        </div>
      </div>

      <div className="card" style={{ padding: 0 }}>
        <table>
          <thead>
            <tr><th>Agent</th><th>User</th><th>Session ID</th><th>Events</th><th>Errors</th><th>Cost</th><th>Duration</th><th>Started</th></tr>
          </thead>
          <tbody>
            {sessions.length ? sessions.map(s => {
              const sid = s.session_id || s.id;
              const cost = s.total_cost_usd ?? s.total_cost ?? 0;
              const events = s.event_count ?? (s.total_llm_calls + s.total_tool_calls + s.total_steps) ?? 0;
              const dur = s.duration ?? ((s.ended_at && s.started_at) ? (s.ended_at - s.started_at) : null);
              return (
              <tr key={sid} style={{ cursor: 'pointer' }} onClick={() => onNavigate('session-detail', { id: sid })}>
                <td style={{ color: '#111827', fontWeight: 600 }}>{s.agent_name || '—'}</td>
                <td style={{ fontSize: 12 }}>{s.user_id || <span className="text-muted">—</span>}</td>
                <td style={{ fontFamily: 'monospace', fontSize: 11 }}>{sid?.slice(0, 12)}...</td>
                <td>{events}</td>
                <td>{(s.error_count || 0) > 0 ? <span className="badge badge-error">{s.error_count}</span> : '0'}</td>
                <td>{fmtCost(cost)}</td>
                <td>{fmtDuration(dur)}</td>
                <td className="text-xs text-muted">{fmtDate(s.started_at)}</td>
              </tr>
              );
            }) : (
              <tr><td colSpan={8} className="empty">No sessions yet</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// Session Detail
function SessionDetailPage({ sessionId, onNavigate }) {
  const [session, setSession] = useState(null);
  const [events, setEvents] = useState([]);
  const [tab, setTab] = useState('tree');
  const [traceTree, setTraceTree] = useState(null);
  const [diffEvent, setDiffEvent] = useState(null);

  useEffect(() => {
    getSession(sessionId)
      .then(r => { setSession(r.session || r); setEvents(r.events || []); })
      .catch(console.error);
    // Load trace tree
    getTraceTree(sessionId).then(setTraceTree).catch(() => {});
  }, [sessionId]);

  if (!session) return <div className="empty">Loading session...</div>;

  const sid = session.session_id || session.id;
  const sessionCost = session.total_cost_usd ?? session.total_cost ?? 0;

  // Normalize event types — API may use dots or underscores
  const matchType = (e, ...types) => types.some(t => e.event_type === t || e.event_type?.replace('.', '_') === t || e.event_type?.includes(t));
  const errors = events.filter(e => matchType(e, 'error', 'llm.error', 'tool.error'));
  const llmCalls = events.filter(e => matchType(e, 'llm_call', 'llm_response', 'llm.response', 'llm.error'));
  const toolCalls = events.filter(e => matchType(e, 'tool_call', 'tool_error', 'tool.call', 'tool.error', 'tool.result'));
  const retries = events.filter(e => matchType(e, 'retry'));

  return (
    <div>
      <div className="flex items-center gap-3 mb-4">
        <button className="btn btn-ghost btn-sm" onClick={() => onNavigate('sessions')}>← Back</button>
        <div>
          <h1 className="page-title" style={{ fontSize: 18 }}>{session.agent_name || 'Session'}</h1>
          <p className="text-xs text-muted" style={{ fontFamily: 'monospace' }}>{sid}</p>
        </div>
      </div>

      <div className="stats-grid" style={{ gridTemplateColumns: 'repeat(6, 1fr)' }}>
        <div className="stat-card"><div className="stat-label">Events</div><div className="stat-value" style={{ fontSize: 20 }}>{events.length}</div></div>
        <div className="stat-card"><div className="stat-label">LLM Calls</div><div className="stat-value" style={{ fontSize: 20, color: '#111827' }}>{llmCalls.length}</div></div>
        <div className="stat-card"><div className="stat-label">Tool Calls</div><div className="stat-value" style={{ fontSize: 20, color: THEME.success }}>{toolCalls.length}</div></div>
        <div className="stat-card"><div className="stat-label">Errors</div><div className="stat-value" style={{ fontSize: 20, color: errors.length ? THEME.error : THEME.success }}>{errors.length}</div></div>
        <div className="stat-card"><div className="stat-label">Retries</div><div className="stat-value" style={{ fontSize: 20, color: retries.length ? THEME.warning : THEME.success }}>{retries.length}</div></div>
        <div className="stat-card"><div className="stat-label">Cost</div><div className="stat-value" style={{ fontSize: 20 }}>{fmtCost(sessionCost)}</div></div>
      </div>

      <div className="tabs">
        {['tree', 'timeline', 'graph', 'errors', 'llm', 'tools', 'raw'].map(t => (
          <div key={t} className={`tab ${tab === t ? 'active' : ''}`} onClick={() => setTab(t)}>
            {t === 'llm' ? 'LLM Calls' : t === 'tree' ? '🌳 Trace Tree' : t === 'graph' ? '🔗 Graph' : t.charAt(0).toUpperCase() + t.slice(1)}
            {t === 'errors' && errors.length > 0 && <span style={{ marginLeft: 6, color: THEME.error }}>({errors.length})</span>}
          </div>
        ))}
      </div>

      {/* Prompt Diff Modal */}
      {diffEvent && <PromptDiffModal event={diffEvent} onClose={() => setDiffEvent(null)} />}

      {tab === 'tree' && (
        <div className="card">
          <div className="card-title">
            Trace Tree — Waterfall View
            {traceTree?.stats && (
              <span className="text-xs text-muted">
                {traceTree.stats.total_events} spans · {traceTree.stats.total_duration_ms?.toFixed(0)}ms · {fmtCost(traceTree.stats.total_cost_usd)}
              </span>
            )}
          </div>
          {traceTree?.root_spans?.length ? (
            <div className="trace-tree">
              {traceTree.root_spans.map((root, i) => (
                <TraceNode
                  key={root.id || i} event={root}
                  traceStart={traceTree.stats?.start_time || 0}
                  traceDuration={traceTree.stats?.total_duration_ms || 1000}
                  onEventClick={(e) => {
                    if (e.event_type?.includes('llm')) setDiffEvent(e);
                  }}
                />
              ))}
            </div>
          ) : events.length > 0 ? (
            // Fallback: show flat events as tree nodes
            <div className="trace-tree">
              {events.map((e, i) => {
                const data = typeof e.data === 'string' ? JSON.parse(e.data || '{}') : (e.data || {});
                const treeEvent = { ...e, ...data, children: [] };
                return (
                  <TraceNode key={i} event={treeEvent} traceStart={events[0]?.timestamp || 0}
                    traceDuration={(events[events.length - 1]?.timestamp - events[0]?.timestamp) * 1000 || 1000}
                    onEventClick={(ev) => { if (ev.event_type?.includes('llm')) setDiffEvent(ev); }}
                  />
                );
              })}
            </div>
          ) : <div className="empty">No trace data available</div>}
        </div>
      )}

      {tab === 'graph' && (
        <AgentGraphView sessionId={sessionId} />
      )}

      {tab === 'timeline' && (
        <div className="timeline">
          {events.map((e, i) => {
            const dur = e.duration_ms || e.latency_ms;
            return (
              <div className="timeline-item" key={i}>
                <div className="timeline-dot" style={{ background: EVENT_COLORS[e.event_type] || THEME.textMuted }} />
                <div className="timeline-content">
                  <div className="flex justify-between">
                    <div className="timeline-title">
                      <span className={`badge badge-${eventBadge(e.event_type)}`} style={{ marginRight: 8 }}>{e.event_type}</span>
                      {e.tool_name || e.model || e.error_type || ''}
                    </div>
                    <span className="timeline-time">{fmtTime(e.timestamp)}</span>
                  </div>
                  <div className="timeline-detail">
                    {dur > 0 && <span>{fmtDuration(dur / 1000)} </span>}
                    {e.total_tokens > 0 && <span>{e.total_tokens} tokens </span>}
                    {e.cost_usd > 0 && <span>{fmtCost(e.cost_usd)} </span>}
                    {e.error_message && <span style={{ color: THEME.error }}>{e.error_message}</span>}
                    {e.tool_result && <span style={{ color: THEME.textMuted }}> {String(e.tool_result).slice(0, 100)}</span>}
                  </div>
                </div>
              </div>
            );
          })}
          {events.length === 0 && <div className="empty">No events in this session</div>}
        </div>
      )}

      {tab === 'errors' && (
        <div className="card">
          {errors.length ? errors.map((e, i) => (
              <div key={i} style={{ padding: '12px 0', borderBottom: `1px solid ${THEME.border}` }}>
                <div className="flex items-center gap-2">
                  <span className="badge badge-error">{e.error_type || e.event_type || 'Error'}</span>
                  <span className="text-xs text-muted">{e.model || e.tool_name || ''}</span>
                  <span className="text-xs text-muted">{fmtTime(e.timestamp)}</span>
                </div>
                <p style={{ margin: '8px 0 4px', color: THEME.error, fontSize: 13 }}>{e.error_message || 'Unknown error'}</p>
                {e.stack_trace && (
                  <pre className="code-block" style={{ fontSize: 11, maxHeight: 150, overflow: 'auto', marginTop: 8 }}>
                    {e.stack_trace}
                  </pre>
                )}
              </div>
          )) : <div className="empty">No errors in this session</div>}
        </div>
      )}

      {tab === 'llm' && (
        <div className="card" style={{ padding: 0 }}>
          <table>
            <thead><tr><th>Model</th><th>Tokens</th><th>Cost</th><th>Latency</th><th>Status</th><th>Time</th></tr></thead>
            <tbody>
              {llmCalls.length ? llmCalls.map((e, i) => {
                const isErr = e.event_type?.includes('error') || e.success === false || e.success === 0;
                return (
                  <tr key={i} style={{ background: isErr ? 'rgba(220,38,38,0.04)' : 'transparent' }}>
                    <td style={{ fontFamily: 'monospace', fontSize: 12 }}>{e.model || '—'}</td>
                    <td>{e.total_tokens || e.input_tokens || '—'}</td>
                    <td>{fmtCost(e.cost_usd || 0)}</td>
                    <td>{e.latency_ms ? fmtDuration(e.latency_ms / 1000) : '—'}</td>
                    <td>{isErr ? <span className="badge badge-error">error</span> : <span className="badge badge-success">ok</span>}</td>
                    <td className="text-xs text-muted">{fmtTime(e.timestamp)}</td>
                  </tr>
                );
              }) : <tr><td colSpan={6} className="empty">No LLM calls</td></tr>}
            </tbody>
          </table>
        </div>
      )}

      {tab === 'tools' && (
        <div className="card" style={{ padding: 0 }}>
          <table>
            <thead><tr><th>Tool</th><th>Duration</th><th>Status</th><th>Result</th><th>Time</th></tr></thead>
            <tbody>
              {toolCalls.length ? toolCalls.map((e, i) => {
                const isErr = e.event_type?.includes('error') || e.success === false || e.success === 0;
                return (
                  <tr key={i} style={{ background: isErr ? 'rgba(220,38,38,0.04)' : 'transparent' }}>
                    <td style={{ color: isErr ? THEME.error : THEME.success, fontWeight: 600 }}>{e.tool_name || '—'}</td>
                    <td>{e.duration_ms ? fmtDuration(e.duration_ms / 1000) : '—'}</td>
                    <td><span className={`badge ${isErr ? 'badge-error' : 'badge-success'}`}>{isErr ? 'failed' : 'ok'}</span></td>
                    <td className="text-xs" style={{ maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis' }}>{String(e.tool_result || e.error_message || '').slice(0, 80)}</td>
                    <td className="text-xs text-muted">{fmtTime(e.timestamp)}</td>
                  </tr>
                );
              }) : <tr><td colSpan={5} className="empty">No tool calls</td></tr>}
            </tbody>
          </table>
        </div>
      )}

      {tab === 'raw' && (
        <pre className="code-block" style={{ maxHeight: 500, overflow: 'auto' }}>
          {JSON.stringify(events, null, 2)}
        </pre>
      )}
    </div>
  );
}

// Live Feed
function LivePage() {
  const [events, setEvents] = useState([]);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef(null);

  useEffect(() => {
    // Initial load via HTTP
    getLiveEvents().then(r => setEvents(r.events || r || [])).catch(() => {});

    // WebSocket for real-time
    const conn = connectLiveWS('default',
      (event) => setEvents(prev => [event, ...prev].slice(0, 200)),
      (alert) => console.log('[Alert]', alert)
    );
    wsRef.current = conn;
    setConnected(true);

    return () => { conn.close(); };
  }, []);

  return (
    <div>
      <div className="flex justify-between items-center mb-4">
        <div>
          <h1 className="page-title">Live Feed</h1>
          <p className="page-subtitle">Real-time agent events via WebSocket</p>
        </div>
        <div className="flex items-center gap-2">
          <span className="health-dot" style={{ background: connected ? THEME.success : THEME.error }} />
          <span className="text-xs">{connected ? 'Connected' : 'Disconnected'}</span>
        </div>
      </div>

      <div className="card" style={{ padding: 0, maxHeight: '70vh', overflowY: 'auto' }}>
        <table>
          <thead><tr><th>Type</th><th>Agent</th><th>Detail</th><th>Time</th></tr></thead>
          <tbody>
            {events.length ? events.map((e, i) => {
              return (
                <tr key={i}>
                  <td><span className={`badge badge-${eventBadge(e.event_type)}`}>{e.event_type}</span></td>
                  <td style={{ color: '#111827', fontWeight: 600 }}>{e.agent_name || '—'}</td>
                  <td className="text-xs">{e.tool_name || e.model || e.error_type || e.decision || '—'}</td>
                  <td className="text-xs text-muted">{fmtTime(e.timestamp)}</td>
                </tr>
              );
            }) : <tr><td colSpan={4} className="empty">Waiting for events... Run an instrumented agent to see live data.</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// Alerts
function AlertsPage({ toast }) {
  const [alerts, setAlerts] = useState([]);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ name: '', condition_type: 'cost', threshold: 10, webhook_url: '' });

  const load = () => getAlerts().then(r => setAlerts(r.rules || r || [])).catch(() => {});
  useEffect(() => { load(); }, []);

  const handleCreate = async () => {
    try {
      await createAlert(form);
      toast('Alert rule created', 'success');
      setShowForm(false);
      setForm({ name: '', condition_type: 'cost', threshold: 10, webhook_url: '' });
      load();
    } catch (e) {
      toast('Failed to create alert: ' + e.message, 'error');
    }
  };

  const handleDelete = async (id) => {
    try {
      await deleteAlert(id);
      toast('Alert deleted', 'success');
      load();
    } catch (e) {
      toast('Failed: ' + e.message, 'error');
    }
  };

  return (
    <div>
      <div className="flex justify-between items-center mb-4">
        <div>
          <h1 className="page-title">Alerts</h1>
          <p className="page-subtitle">Set up alert rules with webhook notifications</p>
        </div>
        <button className="btn btn-primary" onClick={() => setShowForm(!showForm)}>
          {showForm ? 'Cancel' : '+ New Alert Rule'}
        </button>
      </div>

      {showForm && (
        <div className="card mb-4">
          <div className="card-title">New Alert Rule</div>
          <div className="flex flex-wrap gap-3" style={{ marginBottom: 12 }}>
            <input className="input" placeholder="Rule name" value={form.name}
              onChange={e => setForm({ ...form, name: e.target.value })} style={{ flex: 1 }} />
            <select className="input" value={form.condition_type}
              onChange={e => setForm({ ...form, condition_type: e.target.value })}>
              <option value="error_rate">Error Rate %</option>
              <option value="cost">Cost Threshold $</option>
              <option value="latency">Latency Avg (ms)</option>
              <option value="failure_streak">Failure Streak</option>
            </select>
            <input className="input" type="number" placeholder="Threshold" value={form.threshold}
              onChange={e => setForm({ ...form, threshold: +e.target.value })} style={{ width: 100 }} />
          </div>
          <div className="flex gap-3">
            <input className="input" placeholder="Webhook URL (Slack, Discord, PagerDuty...)" value={form.webhook_url}
              onChange={e => setForm({ ...form, webhook_url: e.target.value })} style={{ flex: 1 }} />
            <button className="btn btn-primary" onClick={handleCreate}>Create Rule</button>
          </div>
        </div>
      )}

      <div className="card">
        {alerts.length ? alerts.map(a => (
          <div className="alert-row" key={a.id || a.rule_id}>
            <div style={{ flex: 1 }}>
              <div style={{ fontWeight: 600, fontSize: 14 }}>{a.name}</div>
              <div className="text-xs text-muted">
                When <span className="badge badge-warning" style={{ margin: '0 4px' }}>{a.condition_type}</span>
                exceeds <strong>{a.threshold}</strong>
              </div>
            </div>
            <div className="text-xs text-muted" style={{ maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis' }}>
              {a.webhook_url || 'No webhook'}
            </div>
            <span className={`badge ${a.enabled !== false ? 'badge-success' : 'badge-default'}`}>
              {a.enabled !== false ? 'active' : 'paused'}
            </span>
            <button className="btn btn-danger btn-sm" onClick={() => handleDelete(a.id || a.rule_id)}>Delete</button>
          </div>
        )) : <div className="empty">No alert rules configured. Create one to get notified of anomalies.</div>}
      </div>
    </div>
  );
}

// Anomalies
function AnomaliesPage({ toast }) {
  const [anomalies, setAnomalies] = useState([]);
  const [trends, setTrends] = useState([]);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    try {
      const [a, t] = await Promise.all([getAnomalies(100), getCostTrends(30)]);
      setAnomalies(a.anomalies || []);
      setTrends(t.trends || []);
    } catch (e) { console.error(e); }
    setLoading(false);
  };

  useEffect(() => { load(); }, []);

  const handleAck = async (id) => {
    try {
      await acknowledgeAnomaly(id);
      toast('Anomaly acknowledged', 'success');
      load();
    } catch (e) { toast('Failed: ' + e.message, 'error'); }
  };

  const handleDetect = async () => {
    try {
      const r = await triggerAnomalyDetection();
      toast(`Detected ${r.anomalies_detected} anomalies`, 'success');
      load();
    } catch (e) { toast('Detection failed: ' + e.message, 'error'); }
  };

  // Simple cost trend chart
  const maxCost = Math.max(...trends.map(t => t.daily_cost || 0), 0.01);

  return (
    <div>
      <div className="flex justify-between items-center mb-4">
        <div>
          <h1 className="page-title">Cost Anomalies</h1>
          <p className="page-subtitle">Automatic detection — alerts when daily cost exceeds 2× rolling average</p>
        </div>
        <button className="btn btn-primary" onClick={handleDetect}>Run Detection Now</button>
      </div>

      {/* Cost Trend Chart */}
      {trends.length > 0 && (
        <div className="card" style={{ marginBottom: 18 }}>
          <div className="card-title">30-Day Cost Trend</div>
          <div style={{ display: 'flex', alignItems: 'flex-end', height: 120, gap: 2, padding: '0 4px' }}>
            {trends.slice(-30).map((t, i) => {
              const height = maxCost > 0 ? ((t.daily_cost || 0) / maxCost) * 100 : 0;
              const isSpike = t.daily_cost > (t.rolling_avg_7d || 0) * 2 && t.rolling_avg_7d > 0;
              return (
                <div key={i} title={`${t.date}: $${(t.daily_cost || 0).toFixed(4)} (avg: $${(t.rolling_avg_7d || 0).toFixed(4)})`}
                  style={{ flex: 1, background: isSpike ? THEME.error : THEME.primary, height: `${Math.max(height, 2)}%`,
                    borderRadius: '3px 3px 0 0', opacity: isSpike ? 1 : 0.6, transition: 'height 0.3s', cursor: 'pointer' }} />
              );
            })}
          </div>
          <div className="flex justify-between text-xs text-muted" style={{ marginTop: 6 }}>
            <span>{trends[0]?.date || ''}</span>
            <span>{trends[trends.length - 1]?.date || ''}</span>
          </div>
        </div>
      )}

      {/* Anomaly List */}
      {loading ? <div className="empty">Loading anomalies...</div> : anomalies.length ? (
        anomalies.map(a => (
          <div key={a.id} className={`anomaly-card ${a.acknowledged ? 'acknowledged' : ''}`}>
            <div className="flex justify-between items-center">
              <div className="flex items-center gap-3">
                <span className="spike-badge">{a.spike_ratio?.toFixed(1)}× spike</span>
                <span style={{ fontWeight: 700 }}>{a.agent_name || 'Unknown Agent'}</span>
                <span className="text-xs text-muted">{a.anomaly_type}</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-xs text-muted">{fmtDate(a.detected_at)}</span>
                {!a.acknowledged && (
                  <button className="btn btn-ghost btn-sm" onClick={() => handleAck(a.id)}>Acknowledge</button>
                )}
              </div>
            </div>
            <div className="flex gap-3 mt-2 text-xs">
              <span>Daily: <strong>{fmtCost(a.current_value)}</strong></span>
              <span>Baseline: <strong>{fmtCost(a.baseline_value)}</strong></span>
              <span>Spike: <strong>{a.spike_ratio?.toFixed(1)}×</strong></span>
            </div>
          </div>
        ))
      ) : (
        <div className="empty">No cost anomalies detected. All spending within normal range.</div>
      )}
    </div>
  );
}

// Admin
function AdminPage({ toast }) {
  const [stats, setStats] = useState(null);
  const [health, setHealth] = useState(null);
  const [cleanupDays, setCleanupDays] = useState(30);
  const [cleaning, setCleaning] = useState(false);
  const [loadingDemo, setLoadingDemo] = useState(false);

  useEffect(() => {
    getAdminStats().then(setStats).catch(() => {});
    getHealth().then(setHealth).catch(() => {});
  }, []);

  const handleCleanup = async () => {
    setCleaning(true);
    try {
      const r = await cleanupData(cleanupDays);
      toast(`Cleaned up ${r.events_deleted || r.deleted_events || 0} events, ${r.sessions_deleted || r.deleted_sessions || 0} sessions`, 'success');
      getAdminStats().then(setStats);
    } catch (e) {
      toast('Cleanup failed: ' + e.message, 'error');
    } finally {
      setCleaning(false);
    }
  };

  return (
    <div>
      <h1 className="page-title">Admin</h1>
      <p className="page-subtitle">System health, database stats, and data retention</p>

      <div className="stats-grid" style={{ gridTemplateColumns: 'repeat(4, 1fr)' }}>
        <div className="stat-card">
          <div className="stat-label">DB Size</div>
          <div className="stat-value" style={{ fontSize: 20 }}>{stats?.db_size_mb?.toFixed(1) || '—'} MB</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Total Events</div>
          <div className="stat-value" style={{ fontSize: 20 }}>{fmt(stats?.total_events)}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Total Sessions</div>
          <div className="stat-value" style={{ fontSize: 20 }}>{fmt(stats?.total_sessions)}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Status</div>
          <div className="stat-value" style={{ fontSize: 20, color: (health?.status === 'ok' || health?.status === 'healthy') ? THEME.success : THEME.error }}>
            {health?.status === 'ok' ? 'Healthy' : health?.status || '—'}
          </div>
        </div>
      </div>

      <div className="card">
        <div className="card-title">Data Retention</div>
        <p className="text-sm text-muted mb-4">Clean up events and sessions older than a specified number of days.</p>
        <div className="flex items-center gap-3">
          <span className="text-sm">Delete data older than</span>
          <input className="input" type="number" value={cleanupDays} min={1}
            onChange={e => setCleanupDays(+e.target.value)} style={{ width: 80 }} />
          <span className="text-sm">days</span>
          <button className="btn btn-danger" onClick={handleCleanup} disabled={cleaning}>
            {cleaning ? 'Cleaning...' : 'Run Cleanup'}
          </button>
        </div>
      </div>

      {health && (
        <div className="card">
          <div className="card-title">Health Check</div>
          <pre className="code-block">{JSON.stringify(health, null, 2)}</pre>
        </div>
      )}

      <div className="card">
        <div className="card-title">Load Demo Data</div>
        <p className="text-sm text-muted mb-4">
          Generate ~500 realistic events across 5 agent types. Includes cost spikes, errors, and nested traces.
        </p>
        <button className="btn btn-primary" onClick={async () => {
          setLoadingDemo(true);
          try {
            const r = await loadDemoData();
            toast(`Loaded ${r.inserted} demo events across ${r.agents?.length} agents!`, 'success');
            getAdminStats().then(setStats);
          } catch (e) { toast('Failed: ' + e.message, 'error'); }
          setLoadingDemo(false);
        }} disabled={loadingDemo}>
          {loadingDemo ? 'Generating...' : '🎲 Load Demo Data'}
        </button>
      </div>
    </div>
  );
}

// Setup
function SetupPage() {
  return (
    <div>
      <h1 className="page-title">Setup Guide</h1>
      <p className="page-subtitle">Instrument your AI agents in 3 lines</p>

      <div className="card">
        <div className="card-title">1. Install the SDK</div>
        <pre className="code-block">pip install agentlens</pre>
      </div>

      <div className="card">
        <div className="card-title">2. Initialize & Monitor</div>
        <pre className="code-block">{`from agentlens import AgentLens, monitor, tool, step

lens = AgentLens(
    server_url="http://localhost:8340",
    project="my-project",
    api_key="your-api-key",  # optional
    sample_rate=1.0,         # 1.0 = capture everything
)

@monitor(agent="my-agent")
def run_agent(query: str):
    # Agent logic here...
    pass

@tool()
def search_db(query: str):
    return db.search(query)

@step()
def process_results(results):
    return summarize(results)`}</pre>
      </div>

      <div className="card">
        <div className="card-title">3. Auto-Patch OpenAI (optional)</div>
        <pre className="code-block">{`from agentlens.integrations.openai import patch_openai
patch_openai()  # Automatically captures all OpenAI calls`}</pre>
      </div>

      <div className="card">
        <div className="card-title">Features</div>
        <table>
          <tbody>
            <tr><td style={{ fontWeight: 600 }}>Error Handling</td><td>Auto-captures all exceptions with stack traces. Retry + fallback decorators included.</td></tr>
            <tr><td style={{ fontWeight: 600 }}>Circuit Breaker</td><td>SDK stops hammering your server after 5 consecutive failures. Auto-recovers after 30s.</td></tr>
            <tr><td style={{ fontWeight: 600 }}>Dead Letter Queue</td><td>Failed events saved to disk, auto-replayed when connection recovers.</td></tr>
            <tr><td style={{ fontWeight: 600 }}>Graceful Shutdown</td><td>All buffered events are drained on process exit (SIGTERM/SIGINT).</td></tr>
            <tr><td style={{ fontWeight: 600 }}>Sampling</td><td>Set sample_rate=0.1 to only capture 10% of sessions in production.</td></tr>
            <tr><td style={{ fontWeight: 600 }}>Alert Webhooks</td><td>Configure rules to fire Slack/Discord/PagerDuty webhooks on anomalies.</td></tr>
            <tr><td style={{ fontWeight: 600 }}>Data Retention</td><td>Admin cleanup endpoint auto-purges old data beyond retention policy.</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ─── App Shell ──────────────────────────────────────────────
function App() {
  const [page, setPage] = useState('overview');
  const [pageParams, setPageParams] = useState({});
  const [health, setHealth] = useState(null);
  const { toast, ToastContainer } = useToast();

  const navigate = (p, params = {}) => { setPage(p); setPageParams(params); };

  useEffect(() => {
    getHealth().then(setHealth).catch(() => setHealth({ status: 'unreachable' }));
    const iv = setInterval(() => {
      getHealth().then(setHealth).catch(() => setHealth({ status: 'unreachable' }));
    }, 30000);
    return () => clearInterval(iv);
  }, []);

  const NAV = [
    { id: 'overview', label: 'Overview', icon: '📊' },
    { id: 'sessions', label: 'Sessions', icon: '📋' },
    { id: 'live', label: 'Live Feed', icon: '⚡' },
    { id: 'anomalies', label: 'Anomalies', icon: '🔥' },
    { id: 'alerts', label: 'Alerts', icon: '🔔' },
    { id: 'admin', label: 'Admin', icon: '⚙️' },
    { id: 'setup', label: 'Setup', icon: '📖' },
  ];

  const renderPage = () => {
    switch (page) {
      case 'overview': return <OverviewPage onNavigate={navigate} />;
      case 'sessions': return <SessionsPage onNavigate={navigate} initialAgent={pageParams.agent} />;
      case 'session-detail': return <SessionDetailPage sessionId={pageParams.id} onNavigate={navigate} />;
      case 'live': return <LivePage />;
      case 'anomalies': return <AnomaliesPage toast={toast} />;
      case 'alerts': return <AlertsPage toast={toast} />;
      case 'admin': return <AdminPage toast={toast} />;
      case 'setup': return <SetupPage />;
      default: return <OverviewPage onNavigate={navigate} />;
    }
  };

  const healthColor = (health?.status === 'healthy' || health?.status === 'ok') ? THEME.success : health?.status === 'unreachable' ? THEME.error : THEME.warning;

  return (
    <>
      <style>{css}</style>
      <ToastContainer />
      <div className="container">
        <aside className="sidebar">
          <div className="sidebar-brand">🔭 AgentLens</div>
          <nav className="sidebar-nav">
            {NAV.map(n => (
              <div key={n.id} className={`nav-item ${page === n.id ? 'active' : ''}`}
                onClick={() => navigate(n.id)}>
                <span>{n.icon}</span> {n.label}
              </div>
            ))}
          </nav>
          <div className="sidebar-footer">
            <span className="health-dot" style={{ background: healthColor }} />
            Server: {health?.status || 'checking...'}
            <br />
            <span style={{ marginTop: 4, display: 'block' }}>v0.3.0 — Production</span>
          </div>
        </aside>
        <main className="main">
          <ErrorBoundary>
            {renderPage()}
          </ErrorBoundary>
        </main>
      </div>
    </>
  );
}

export default App;
