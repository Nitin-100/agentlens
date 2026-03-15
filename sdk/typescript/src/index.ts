/**
 * @agentlens/sdk — TypeScript SDK for AI Agent Observability
 *
 * Usage:
 *   import { AgentLens } from '@agentlens/sdk';
 *
 *   const lens = new AgentLens({
 *     serverUrl: 'http://localhost:8340',
 *     agentName: 'my-agent',
 *   });
 *
 *   lens.startSession();
 *   lens.trackLLMCall({ model: 'gpt-4o', prompt: 'Hello', completion: 'Hi!' });
 *   await lens.shutdown();
 */

export { AgentLens } from "./client";
export { patchOpenAI, patchOpenAIEmbeddings } from "./patches/openai";
export { patchAnthropic } from "./patches/anthropic";
export type {
  AgentLensConfig,
  AgentLensEvent,
  EventType,
  TrackLLMCallArgs,
  TrackToolCallArgs,
  TrackStepArgs,
  TrackErrorArgs,
  HealthResponse,
  AnalyticsResponse,
  TraceTree,
  CostAnomaly,
  SessionSummary,
} from "./types";
