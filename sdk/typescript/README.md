# @agentlens/sdk — TypeScript SDK

Full type-safe TypeScript SDK for AgentLens AI Agent Observability.

## Install

```bash
npm install @agentlens/sdk
```

## Quick Start

```typescript
import { AgentLens } from '@agentlens/sdk';

const lens = new AgentLens({
  serverUrl: 'http://localhost:8340',
  agentName: 'my-agent',
});

// Start a session
const sessionId = lens.startSession('my-agent');

// Track LLM calls
lens.trackLLMCall({
  model: 'gpt-4o',
  prompt: 'What is the weather?',
  completion: 'I need to check the weather tool.',
  inputTokens: 15,
  outputTokens: 12,
  costUsd: 0.002,
  latencyMs: 450,
});

// Track tool usage
lens.trackToolCall({
  toolName: 'get_weather',
  toolArgs: { location: 'NYC' },
  toolResult: { temp: 72, condition: 'sunny' },
  durationMs: 200,
});

// Track errors
lens.trackError({
  errorType: 'RateLimitError',
  errorMessage: 'Too many requests',
});

// End session
lens.endSession(true);

// Shutdown (flushes all buffered events)
await lens.shutdown();
```

## Auto-Patch OpenAI

```typescript
import { AgentLens, patchOpenAI } from '@agentlens/sdk';
import OpenAI from 'openai';

const lens = new AgentLens({ serverUrl: 'http://localhost:8340' });
const openai = new OpenAI();

// Automatically track all OpenAI calls
patchOpenAI(openai, lens);

// This call is now auto-tracked
const response = await openai.chat.completions.create({
  model: 'gpt-4o',
  messages: [{ role: 'user', content: 'Hello!' }],
});
```

## Auto-Patch Anthropic

```typescript
import { AgentLens, patchAnthropic } from '@agentlens/sdk';
import Anthropic from '@anthropic-ai/sdk';

const lens = new AgentLens({ serverUrl: 'http://localhost:8340' });
const anthropic = new Anthropic();

patchAnthropic(anthropic, lens);

const response = await anthropic.messages.create({
  model: 'claude-sonnet-4-20250514',
  messages: [{ role: 'user', content: 'Hello!' }],
  max_tokens: 1024,
});
```

## Features

- **Full TypeScript types** — autocomplete for all events and APIs
- **Auto-batching** — events buffered and sent in batches (configurable)
- **Circuit breaker** — stops hammering server after 5 failures, recovers after 30s
- **Sampling** — set `sampleRate: 0.1` to only capture 10% in production
- **Function wrappers** — `wrapLLM()` and `wrapTool()` for automatic tracking
- **Query API** — fetch sessions, analytics, traces, anomalies
- **Zero dependencies** — uses native `fetch()`
