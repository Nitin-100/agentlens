/**
 * AgentLens — OpenAI Auto-Patch for TypeScript
 *
 * Automatically intercepts all OpenAI chat.completions.create() calls
 * and tracks them as LLM events.
 *
 * Usage:
 *   import { AgentLens } from '@agentlens/sdk';
 *   import { patchOpenAI } from '@agentlens/sdk/patches/openai';
 *
 *   const lens = new AgentLens({ serverUrl: 'http://localhost:8340' });
 *   const openai = new OpenAI();
 *   patchOpenAI(openai, lens);
 *
 *   // All subsequent calls are auto-tracked
 *   const result = await openai.chat.completions.create({ ... });
 */

import type { AgentLens } from "../client";

/**
 * Patch an OpenAI client instance to auto-track all chat completion calls.
 */
export function patchOpenAI(openaiClient: any, lens: AgentLens): void {
  if (!openaiClient?.chat?.completions?.create) {
    console.warn("[AgentLens] OpenAI client does not have chat.completions.create");
    return;
  }

  const originalCreate = openaiClient.chat.completions.create.bind(
    openaiClient.chat.completions
  );

  openaiClient.chat.completions.create = async function (
    params: any,
    options?: any
  ) {
    const start = Date.now();
    try {
      const result = await originalCreate(params, options);
      const latencyMs = Date.now() - start;

      const usage = result.usage;
      const choice = result.choices?.[0];

      // Extract prompt from messages
      const messages = params.messages || [];
      const prompt = messages
        .map((m: any) => `[${m.role}]: ${m.content || ""}`)
        .join("\n");

      lens.trackLLMCall({
        model: params.model || result.model || "unknown",
        provider: "openai",
        prompt,
        completion: choice?.message?.content || "",
        inputTokens: usage?.prompt_tokens,
        outputTokens: usage?.completion_tokens,
        latencyMs,
        success: true,
        meta: {
          finish_reason: choice?.finish_reason,
          tool_calls: choice?.message?.tool_calls?.length || 0,
          temperature: params.temperature,
          max_tokens: params.max_tokens,
        },
      });

      return result;
    } catch (e) {
      lens.trackError({
        errorType: "openai_error",
        errorMessage: e instanceof Error ? e.message : String(e),
        stackTrace: e instanceof Error ? e.stack : undefined,
        meta: { model: params.model, provider: "openai" },
      });
      throw e;
    }
  };
}

/**
 * Patch an OpenAI client to also track embeddings calls.
 */
export function patchOpenAIEmbeddings(openaiClient: any, lens: AgentLens): void {
  if (!openaiClient?.embeddings?.create) return;

  const originalCreate = openaiClient.embeddings.create.bind(
    openaiClient.embeddings
  );

  openaiClient.embeddings.create = async function (
    params: any,
    options?: any
  ) {
    const start = Date.now();
    try {
      const result = await originalCreate(params, options);
      lens.trackLLMCall({
        model: params.model || "text-embedding-ada-002",
        provider: "openai",
        inputTokens: result.usage?.total_tokens,
        latencyMs: Date.now() - start,
        success: true,
        meta: { type: "embedding", dimensions: result.data?.[0]?.embedding?.length },
      });
      return result;
    } catch (e) {
      lens.trackError({
        errorType: "openai_embeddings_error",
        errorMessage: e instanceof Error ? e.message : String(e),
      });
      throw e;
    }
  };
}
