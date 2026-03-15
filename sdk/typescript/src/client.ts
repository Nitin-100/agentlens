/**
 * AgentLens TypeScript SDK — Core Client
 *
 * Full-featured, type-safe SDK for AI agent observability.
 * Auto-batching, circuit breaker, and graceful shutdown included.
 *
 * Usage:
 *   import { AgentLens } from '@agentlens/sdk';
 *   const lens = new AgentLens({ serverUrl: 'http://localhost:8340' });
 *   lens.startSession('my-agent');
 *   lens.trackLLMCall({ model: 'gpt-4o', prompt: 'Hello', completion: 'Hi!' });
 *   await lens.shutdown();
 */

import type {
  AgentLensConfig,
  AgentLensEvent,
  TrackLLMCallArgs,
  TrackToolCallArgs,
  TrackStepArgs,
  TrackErrorArgs,
  HealthResponse,
  AnalyticsResponse,
  TraceTree,
  CostAnomaly,
} from "./types";

export class AgentLens {
  private serverUrl: string;
  private apiKey?: string;
  private projectId: string;
  private agentName: string;
  private batchSize: number;
  private flushIntervalMs: number;
  private sampleRate: number;
  private debug: boolean;

  private buffer: AgentLensEvent[] = [];
  private sessionId: string | null = null;
  private parentId: string | null = null;
  private timer: ReturnType<typeof setInterval> | null = null;

  // Circuit breaker
  private consecutiveFailures = 0;
  private circuitOpen = false;
  private circuitResetAt = 0;

  constructor(config: AgentLensConfig) {
    this.serverUrl = config.serverUrl.replace(/\/$/, "");
    this.apiKey = config.apiKey;
    this.projectId = config.projectId ?? "default";
    this.agentName = config.agentName ?? "default";
    this.batchSize = config.batchSize ?? 50;
    this.flushIntervalMs = config.flushIntervalMs ?? 5000;
    this.sampleRate = config.sampleRate ?? 1.0;
    this.debug = config.debug ?? false;

    this.startAutoFlush();
  }

  // ─── Session Management ─────────────────────────────────

  startSession(agentName?: string): string {
    this.sessionId = `sess_${Date.now()}_${randomId()}`;
    this.addEvent({
      event_type: "session.start",
      session_id: this.sessionId,
      agent_name: agentName ?? this.agentName,
    });
    return this.sessionId;
  }

  endSession(success = true, meta?: Record<string, unknown>): void {
    if (!this.sessionId) return;
    this.addEvent({
      event_type: "session.end",
      session_id: this.sessionId,
      success,
      meta,
    });
    this.sessionId = null;
    this.flush();
  }

  setParentId(parentId: string | null): void {
    this.parentId = parentId;
  }

  getSessionId(): string | null {
    return this.sessionId;
  }

  // ─── Event Tracking ───────────────────────────────────────

  trackLLMCall(args: TrackLLMCallArgs): void {
    this.addEvent({
      event_type: "llm.response",
      model: args.model,
      provider: args.provider,
      prompt: args.prompt,
      completion: args.completion,
      input_tokens: args.inputTokens,
      output_tokens: args.outputTokens,
      total_tokens: (args.inputTokens ?? 0) + (args.outputTokens ?? 0),
      cost_usd: args.costUsd,
      latency_ms: args.latencyMs,
      success: args.success ?? true,
      meta: args.meta,
    });
  }

  trackToolCall(args: TrackToolCallArgs): void {
    const success = args.success ?? true;
    this.addEvent({
      event_type: success ? "tool.result" : "tool.error",
      tool_name: args.toolName,
      tool_args: args.toolArgs,
      tool_result:
        typeof args.toolResult === "string"
          ? args.toolResult
          : JSON.stringify(args.toolResult),
      success,
      duration_ms: args.durationMs,
      meta: args.meta,
    });
  }

  trackStep(args: TrackStepArgs): void {
    this.addEvent({
      event_type: "agent.step",
      step_number: args.stepNumber,
      thought: args.thought,
      decision: args.decision,
      meta: args.meta,
    });
  }

  trackError(args: TrackErrorArgs): void {
    this.addEvent({
      event_type: "error",
      error_type: args.errorType,
      error_message: args.errorMessage,
      stack_trace: args.stackTrace,
      success: false,
      meta: args.meta,
    });
  }

  trackCustom(eventType: string, data: Record<string, unknown>): void {
    this.addEvent({ event_type: eventType, ...data });
  }

  // ─── Decorator-style wrappers ─────────────────────────────

  /**
   * Wrap an async function to auto-track it as an LLM call.
   */
  wrapLLM<T extends (...args: any[]) => Promise<any>>(
    model: string,
    fn: T
  ): T {
    const self = this;
    return (async function (this: any, ...args: any[]) {
      const start = Date.now();
      try {
        const result = await fn.apply(this, args);
        self.trackLLMCall({
          model,
          latencyMs: Date.now() - start,
          success: true,
        });
        return result;
      } catch (e) {
        self.trackError({
          errorMessage: e instanceof Error ? e.message : String(e),
          stackTrace: e instanceof Error ? e.stack : undefined,
        });
        throw e;
      }
    }) as unknown as T;
  }

  /**
   * Wrap an async function to auto-track it as a tool call.
   */
  wrapTool<T extends (...args: any[]) => Promise<any>>(
    toolName: string,
    fn: T
  ): T {
    const self = this;
    return (async function (this: any, ...args: any[]) {
      const start = Date.now();
      try {
        const result = await fn.apply(this, args);
        self.trackToolCall({
          toolName,
          toolArgs: args.length === 1 ? args[0] : { args },
          toolResult: result,
          durationMs: Date.now() - start,
          success: true,
        });
        return result;
      } catch (e) {
        self.trackToolCall({
          toolName,
          toolArgs: args.length === 1 ? args[0] : { args },
          toolResult: e instanceof Error ? e.message : String(e),
          durationMs: Date.now() - start,
          success: false,
        });
        throw e;
      }
    }) as unknown as T;
  }

  // ─── Buffering & Flushing ─────────────────────────────────

  private addEvent(event: Partial<AgentLensEvent>): void {
    // Sampling
    if (this.sampleRate < 1.0 && Math.random() > this.sampleRate) return;

    event.timestamp = event.timestamp ?? Date.now() / 1000;
    event.session_id = event.session_id ?? this.sessionId ?? "";
    event.agent_name = event.agent_name ?? this.agentName;
    event.event_id = `evt_${Date.now()}_${randomId()}`;
    if (this.parentId) event.parent_id = this.parentId;

    this.buffer.push(event as AgentLensEvent);

    if (this.buffer.length >= this.batchSize) {
      this.flush();
    }
  }

  async flush(): Promise<void> {
    if (this.buffer.length === 0) return;

    // Circuit breaker check
    if (this.circuitOpen) {
      if (Date.now() < this.circuitResetAt) {
        this.log("Circuit breaker open, skipping flush");
        return;
      }
      this.circuitOpen = false;
      this.consecutiveFailures = 0;
    }

    const events = [...this.buffer];
    this.buffer = [];

    try {
      const resp = await fetch(`${this.serverUrl}/api/v1/events`, {
        method: "POST",
        headers: this.headers(),
        body: JSON.stringify({ events }),
      });

      if (!resp.ok) {
        const err = await resp.text();
        console.error(`[AgentLens] Flush failed (${resp.status}): ${err}`);
        this.buffer.unshift(...events);
        this.recordFailure();
      } else {
        this.consecutiveFailures = 0;
      }
    } catch (e) {
      console.error(
        `[AgentLens] Flush error: ${e instanceof Error ? e.message : e}`
      );
      this.buffer.unshift(...events);
      this.recordFailure();
    }
  }

  private recordFailure(): void {
    this.consecutiveFailures++;
    if (this.consecutiveFailures >= 5) {
      this.circuitOpen = true;
      this.circuitResetAt = Date.now() + 30000; // Reset after 30s
      console.warn(
        "[AgentLens] Circuit breaker opened — pausing event delivery for 30s"
      );
    }
  }

  private startAutoFlush(): void {
    this.timer = setInterval(() => this.flush(), this.flushIntervalMs);
  }

  async shutdown(): Promise<void> {
    if (this.timer) {
      clearInterval(this.timer);
      this.timer = null;
    }
    await this.flush();
  }

  // ─── Query API ────────────────────────────────────────────

  async getHealth(): Promise<HealthResponse> {
    return this.get<HealthResponse>("/api/health");
  }

  async getSessions(options?: {
    agent?: string;
    limit?: number;
    offset?: number;
  }): Promise<{ sessions: any[]; total: number }> {
    const params = new URLSearchParams();
    if (options?.agent) params.set("agent", options.agent);
    if (options?.limit) params.set("limit", String(options.limit));
    if (options?.offset) params.set("offset", String(options.offset));
    return this.get(`/api/v1/sessions?${params}`);
  }

  async getAnalytics(hours = 24): Promise<AnalyticsResponse> {
    return this.get(`/api/v1/analytics?hours=${hours}`);
  }

  async getTraceTree(traceId: string): Promise<TraceTree> {
    return this.get(`/api/v1/traces/${traceId}`);
  }

  async getAnomalies(limit = 50): Promise<{ anomalies: CostAnomaly[] }> {
    return this.get(`/api/v1/anomalies?limit=${limit}`);
  }

  async loadDemoData(): Promise<{ ok: boolean; inserted: number }> {
    return this.post("/api/v1/demo/load", {});
  }

  // ─── HTTP Helpers ─────────────────────────────────────────

  private headers(): Record<string, string> {
    const h: Record<string, string> = {
      "Content-Type": "application/json",
    };
    if (this.apiKey) h["Authorization"] = `Bearer ${this.apiKey}`;
    if (this.projectId) h["X-Project"] = this.projectId;
    return h;
  }

  private async get<T>(path: string): Promise<T> {
    const resp = await fetch(`${this.serverUrl}${path}`, {
      headers: this.headers(),
    });
    if (!resp.ok) throw new Error(`API error: ${resp.status}`);
    return resp.json() as Promise<T>;
  }

  private async post<T>(
    path: string,
    body: Record<string, unknown>
  ): Promise<T> {
    const resp = await fetch(`${this.serverUrl}${path}`, {
      method: "POST",
      headers: this.headers(),
      body: JSON.stringify(body),
    });
    if (!resp.ok) throw new Error(`API error: ${resp.status}`);
    return resp.json() as Promise<T>;
  }

  private log(...args: unknown[]): void {
    if (this.debug) console.log("[AgentLens]", ...args);
  }
}

function randomId(): string {
  return Math.random().toString(36).substring(2, 10);
}
