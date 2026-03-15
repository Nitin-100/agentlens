/**
 * AgentLens TypeScript SDK — Type definitions
 */

// ─── Event Types ────────────────────────────────────────────

export type EventType =
  | "session.start"
  | "session.end"
  | "llm.response"
  | "tool.call"
  | "tool.result"
  | "tool.error"
  | "agent.step"
  | "error"
  | "retry"
  | "fallback"
  | "custom";

export interface AgentLensEvent {
  event_id?: string;
  event_type: EventType | string;
  timestamp?: number;
  session_id?: string;
  agent_name?: string;
  parent_id?: string;

  // LLM fields
  model?: string;
  provider?: string;
  prompt?: string;
  completion?: string;
  input_tokens?: number;
  output_tokens?: number;
  total_tokens?: number;
  cost_usd?: number;
  latency_ms?: number;

  // Tool fields
  tool_name?: string;
  tool_args?: Record<string, unknown>;
  tool_result?: string;
  duration_ms?: number;

  // Step fields
  step_number?: number;
  thought?: string;
  decision?: string;

  // Error fields
  error_type?: string;
  error_message?: string;
  stack_trace?: string;

  // Status
  success?: boolean;

  // Generic data bag
  meta?: Record<string, unknown>;
  data?: Record<string, unknown>;

  [key: string]: unknown;
}

// ─── Config ─────────────────────────────────────────────────

export interface AgentLensConfig {
  /** AgentLens server URL (e.g. http://localhost:8340) */
  serverUrl: string;
  /** API key (optional if auth not required) */
  apiKey?: string;
  /** Project ID for multi-tenancy */
  projectId?: string;
  /** Default agent name */
  agentName?: string;
  /** Events per batch before auto-flush (default: 50) */
  batchSize?: number;
  /** Auto-flush interval in ms (default: 5000) */
  flushIntervalMs?: number;
  /** Sampling rate 0.0-1.0 (default: 1.0) */
  sampleRate?: number;
  /** Enable debug logging (default: false) */
  debug?: boolean;
}

// ─── Track Method Arguments ─────────────────────────────────

export interface TrackLLMCallArgs {
  model: string;
  provider?: string;
  prompt?: string;
  completion?: string;
  inputTokens?: number;
  outputTokens?: number;
  costUsd?: number;
  latencyMs?: number;
  success?: boolean;
  meta?: Record<string, unknown>;
}

export interface TrackToolCallArgs {
  toolName: string;
  toolArgs?: Record<string, unknown>;
  toolResult?: unknown;
  success?: boolean;
  durationMs?: number;
  meta?: Record<string, unknown>;
}

export interface TrackStepArgs {
  stepNumber?: number;
  thought?: string;
  decision?: string;
  meta?: Record<string, unknown>;
}

export interface TrackErrorArgs {
  errorType?: string;
  errorMessage: string;
  stackTrace?: string;
  meta?: Record<string, unknown>;
}

// ─── API Response Types ─────────────────────────────────────

export interface HealthResponse {
  status: "healthy" | "degraded" | "unhealthy";
  version: string;
  uptime_seconds: number;
  database: string;
}

export interface SessionSummary {
  session_id: string;
  agent_name: string;
  started_at: number;
  ended_at?: number;
  event_count: number;
  error_count: number;
  total_cost_usd: number;
  total_tokens: number;
  duration?: number;
}

export interface AnalyticsResponse {
  total_events: number;
  total_sessions: number;
  total_cost_usd: number;
  total_tokens: number;
  total_errors: number;
  avg_latency_ms: number;
  top_agents: Array<{ agent_name: string; sessions: number; errors: number }>;
  top_models: Array<{ model: string; count: number; tokens: number; cost: number }>;
  top_tools: Array<{ tool_name: string; count: number; failures: number; avg_duration: number }>;
  error_types: Array<{ error_type: string; count: number }>;
}

export interface TraceTree {
  trace_id: string;
  root_spans: AgentLensEvent[];
  all_events: AgentLensEvent[];
  stats: {
    total_events: number;
    total_duration_ms: number;
    total_cost_usd: number;
    total_tokens: number;
    start_time: number;
    end_time: number;
  };
}

export interface CostAnomaly {
  id: number;
  project_id: string;
  agent_name: string;
  anomaly_type: string;
  detected_at: string;
  daily_cost: number;
  baseline_cost: number;
  rolling_avg: number;
  spike_ratio: number;
  acknowledged: boolean;
}
