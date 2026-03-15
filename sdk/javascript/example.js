// AgentLens JavaScript SDK — Quick Start Example
// Works with Node.js 18+ (native fetch) or any modern browser

import { AgentLens } from './agentlens.js';

// 1. Initialize
const lens = new AgentLens('http://localhost:8340', 'al_your_api_key', {
    agentName: 'my-js-agent',
    batchSize: 10,
    flushInterval: 3000,
});

// 2. Start a session
const sessionId = lens.startSession('my-js-agent');
console.log(`Session started: ${sessionId}`);

// 3. Track an LLM call
lens.trackLLMCall({
    model: 'gpt-4o',
    provider: 'openai',
    prompt: 'What is the capital of France?',
    completion: 'The capital of France is Paris.',
    inputTokens: 12,
    outputTokens: 8,
    costUsd: 0.0003,
    latencyMs: 450,
});

// 4. Track a tool call
lens.trackToolCall({
    toolName: 'web_search',
    toolArgs: { query: 'Paris population' },
    toolResult: '2.1 million',
    success: true,
    durationMs: 320,
});

// 5. Track a step
lens.trackStep({
    stepNumber: 1,
    thought: 'User asked about France, I should provide geographic info',
    decision: 'Search for more details about Paris',
});

// 6. Track an error (if one occurs)
lens.trackError({
    errorType: 'APIError',
    errorMessage: 'Rate limit exceeded',
    stackTrace: 'at fetch() ...',
});

// 7. End session
lens.endSession(true, {
    total_cost: 0.0003,
    total_tokens: 20,
    llm_calls: 1,
    tool_calls: 1,
});

// 8. Shutdown (flush remaining events)
await lens.shutdown();
console.log('Done! Check dashboard at http://localhost:5173');
