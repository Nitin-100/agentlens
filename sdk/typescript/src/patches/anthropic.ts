/**
 * AgentLens — Anthropic Auto-Patch for TypeScript
 *
 * Usage:
 *   import { AgentLens } from '@agentlens/sdk';
 *   import { patchAnthropic } from '@agentlens/sdk/patches/anthropic';
 *
 *   const lens = new AgentLens({ serverUrl: 'http://localhost:8340' });
 *   const anthropic = new Anthropic();
 *   patchAnthropic(anthropic, lens);
 */

import type { AgentLens } from "../client";

/**
 * Patch an Anthropic client instance to auto-track all messages.create() calls.
 */
export function patchAnthropic(anthropicClient: any, lens: AgentLens): void {
  if (!anthropicClient?.messages?.create) {
    console.warn("[AgentLens] Anthropic client does not have messages.create");
    return;
  }

  const originalCreate = anthropicClient.messages.create.bind(
    anthropicClient.messages
  );

  anthropicClient.messages.create = async function (
    params: any,
    options?: any
  ) {
    const start = Date.now();
    try {
      const result = await originalCreate(params, options);
      const latencyMs = Date.now() - start;

      const messages = params.messages || [];
      const prompt = messages
        .map((m: any) => `[${m.role}]: ${typeof m.content === "string" ? m.content : JSON.stringify(m.content)}`)
        .join("\n");

      const completion = result.content
        ?.map((block: any) => block.text || "")
        .join("\n") || "";

      lens.trackLLMCall({
        model: params.model || result.model || "unknown",
        provider: "anthropic",
        prompt: (params.system ? `[system]: ${params.system}\n` : "") + prompt,
        completion,
        inputTokens: result.usage?.input_tokens,
        outputTokens: result.usage?.output_tokens,
        latencyMs,
        success: true,
        meta: {
          stop_reason: result.stop_reason,
          temperature: params.temperature,
          max_tokens: params.max_tokens,
        },
      });

      return result;
    } catch (e) {
      lens.trackError({
        errorType: "anthropic_error",
        errorMessage: e instanceof Error ? e.message : String(e),
        stackTrace: e instanceof Error ? e.stack : undefined,
        meta: { model: params.model, provider: "anthropic" },
      });
      throw e;
    }
  };
}
