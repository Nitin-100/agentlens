/**
 * AgentLens SDK for JavaScript/TypeScript (Node.js + Browser)
 * 
 * Universal HTTP-based SDK — works anywhere fetch() is available.
 * No dependencies required (uses native fetch in Node 18+ and browsers).
 * 
 * Usage:
 *   const lens = new AgentLens('http://localhost:8340', 'al_your_api_key');
 *   await lens.trackLLMCall({ model: 'gpt-4o', prompt: 'Hello', completion: 'Hi!', latency_ms: 120 });
 * 
 * For older Node.js (< 18), install node-fetch:
 *   npm install node-fetch
 */

class AgentLens {
    /**
     * @param {string} serverUrl - AgentLens server URL (e.g. http://localhost:8340)
     * @param {string} [apiKey] - API key (optional if auth not required)
     * @param {object} [options] - Additional options
     * @param {string} [options.projectId] - Project ID for multi-tenancy
     * @param {string} [options.agentName] - Default agent name
     * @param {number} [options.batchSize] - Events per batch (default: 50)
     * @param {number} [options.flushInterval] - Flush interval in ms (default: 5000)
     */
    constructor(serverUrl, apiKey = null, options = {}) {
        this.serverUrl = serverUrl.replace(/\/$/, '');
        this.apiKey = apiKey;
        this.projectId = options.projectId || 'default';
        this.agentName = options.agentName || 'default';
        this.batchSize = options.batchSize || 50;
        this.flushInterval = options.flushInterval || 5000;

        this._buffer = [];
        this._sessionId = null;
        this._timer = null;
        this._startAutoFlush();
    }

    // ─── Headers ────────────────────────────────────────────

    _headers() {
        const h = { 'Content-Type': 'application/json' };
        if (this.apiKey) h['Authorization'] = `Bearer ${this.apiKey}`;
        if (this.projectId) h['X-Project'] = this.projectId;
        return h;
    }

    // ─── Session Management ─────────────────────────────────

    startSession(agentName = null) {
        this._sessionId = `sess_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
        this._addEvent({
            event_type: 'session.start',
            session_id: this._sessionId,
            agent_name: agentName || this.agentName,
        });
        return this._sessionId;
    }

    endSession(success = true, meta = {}) {
        if (!this._sessionId) return;
        this._addEvent({
            event_type: 'session.end',
            session_id: this._sessionId,
            success,
            meta,
        });
        this._sessionId = null;
        this.flush(); // Flush immediately on session end
    }

    // ─── Event Tracking ─────────────────────────────────────

    trackLLMCall({ model, provider, prompt, completion, inputTokens, outputTokens, costUsd, latencyMs, ...extra }) {
        this._addEvent({
            event_type: 'llm.response',
            model,
            provider,
            prompt,
            completion,
            input_tokens: inputTokens,
            output_tokens: outputTokens,
            total_tokens: (inputTokens || 0) + (outputTokens || 0),
            cost_usd: costUsd,
            latency_ms: latencyMs,
            ...extra,
        });
    }

    trackToolCall({ toolName, toolArgs, toolResult, success = true, durationMs, ...extra }) {
        this._addEvent({
            event_type: success ? 'tool.result' : 'tool.error',
            tool_name: toolName,
            tool_args: toolArgs,
            tool_result: typeof toolResult === 'string' ? toolResult : JSON.stringify(toolResult),
            success,
            duration_ms: durationMs,
            ...extra,
        });
    }

    trackStep({ stepNumber, thought, decision, ...extra }) {
        this._addEvent({
            event_type: 'agent.step',
            step_number: stepNumber,
            thought,
            decision,
            ...extra,
        });
    }

    trackError({ errorType, errorMessage, stackTrace, ...extra }) {
        this._addEvent({
            event_type: 'error',
            error_type: errorType,
            error_message: errorMessage,
            stack_trace: stackTrace,
            success: false,
            ...extra,
        });
    }

    trackCustom(eventData) {
        this._addEvent({ event_type: 'custom', ...eventData });
    }

    // ─── Buffering & Flushing ───────────────────────────────

    _addEvent(event) {
        event.timestamp = event.timestamp || Date.now() / 1000;
        event.session_id = event.session_id || this._sessionId || '';
        event.agent_name = event.agent_name || this.agentName;
        event.event_id = `evt_${Date.now()}_${Math.random().toString(36).substr(2, 6)}`;
        this._buffer.push(event);

        if (this._buffer.length >= this.batchSize) {
            this.flush();
        }
    }

    async flush() {
        if (this._buffer.length === 0) return;

        const events = [...this._buffer];
        this._buffer = [];

        try {
            const resp = await fetch(`${this.serverUrl}/api/v1/events`, {
                method: 'POST',
                headers: this._headers(),
                body: JSON.stringify({ events }),
            });

            if (!resp.ok) {
                const err = await resp.text();
                console.error(`[AgentLens] Flush failed (${resp.status}): ${err}`);
                // Re-add events to buffer for retry
                this._buffer.unshift(...events);
            }
        } catch (e) {
            console.error(`[AgentLens] Flush error: ${e.message}`);
            this._buffer.unshift(...events);
        }
    }

    _startAutoFlush() {
        this._timer = setInterval(() => this.flush(), this.flushInterval);
    }

    async shutdown() {
        if (this._timer) {
            clearInterval(this._timer);
            this._timer = null;
        }
        await this.flush();
    }

    // ─── Query API ──────────────────────────────────────────

    async getSessions(options = {}) {
        const params = new URLSearchParams();
        if (options.agent) params.set('agent', options.agent);
        if (options.limit) params.set('limit', options.limit);
        if (options.offset) params.set('offset', options.offset);

        const resp = await fetch(`${this.serverUrl}/api/v1/sessions?${params}`, {
            headers: this._headers(),
        });
        return resp.json();
    }

    async getAnalytics(hours = 24) {
        const resp = await fetch(`${this.serverUrl}/api/v1/analytics?hours=${hours}`, {
            headers: this._headers(),
        });
        return resp.json();
    }

    async getHealth() {
        const resp = await fetch(`${this.serverUrl}/api/health`);
        return resp.json();
    }
}

// ─── OpenAI Wrapper (auto-instrument) ───────────────────────

/**
 * Wraps an OpenAI client to auto-track all LLM calls.
 * 
 * Usage:
 *   import OpenAI from 'openai';
 *   const openai = new OpenAI();
 *   const lens = new AgentLens('http://localhost:8340', 'al_key');
 *   const trackedOpenAI = lens.wrapOpenAI(openai);
 *   // Now all calls are auto-tracked
 */
AgentLens.prototype.wrapOpenAI = function(openaiClient) {
    const lens = this;
    const original = openaiClient.chat.completions.create.bind(openaiClient.chat.completions);

    openaiClient.chat.completions.create = async function(...args) {
        const start = Date.now();
        try {
            const result = await original(...args);
            const latency = Date.now() - start;
            const model = args[0]?.model || 'unknown';
            const prompt = JSON.stringify(args[0]?.messages || []);

            lens.trackLLMCall({
                model,
                provider: 'openai',
                prompt: prompt.substring(0, 2000),
                completion: result.choices?.[0]?.message?.content?.substring(0, 2000),
                inputTokens: result.usage?.prompt_tokens,
                outputTokens: result.usage?.completion_tokens,
                latencyMs: latency,
            });

            return result;
        } catch (error) {
            lens.trackError({
                errorType: 'openai_error',
                errorMessage: error.message,
                stackTrace: error.stack,
            });
            throw error;
        }
    };

    return openaiClient;
};

// Export for different module systems
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { AgentLens };
}
if (typeof window !== 'undefined') {
    window.AgentLens = AgentLens;
}
export { AgentLens };
