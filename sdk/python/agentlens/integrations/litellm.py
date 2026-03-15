"""
AgentLens LiteLLM Integration — universal proxy for 100+ LLM providers.

LiteLLM is a universal LLM API that supports OpenAI, Anthropic, Google, Mistral,
Cohere, HuggingFace, Ollama, Azure, AWS Bedrock, etc. — all through one interface.

By patching LiteLLM, AgentLens auto-captures calls to ANY LLM provider.

Usage:
    from agentlens.integrations.litellm import patch_litellm
    patch_litellm()

    # Now ANY litellm.completion() or litellm.acompletion() is tracked
    import litellm
    litellm.completion(model="gpt-4o", messages=[...])
    litellm.completion(model="claude-3-sonnet", messages=[...])
    litellm.completion(model="gemini/gemini-pro", messages=[...])
    litellm.completion(model="ollama/llama3", messages=[...])
"""

import time
import functools
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ..client import AgentLens


def patch_litellm(lens: Optional["AgentLens"] = None):
    """Patch litellm.completion and litellm.acompletion to auto-track all LLM calls."""
    try:
        import litellm
    except ImportError:
        raise ImportError("litellm not installed. Run: pip install litellm")

    if lens is None:
        from ..client import AgentLens
        lens = AgentLens.get_instance()
        if not lens:
            raise ValueError("No AgentLens instance found.")

    # Patch sync completion
    original_completion = litellm.completion

    @functools.wraps(original_completion)
    def patched_completion(*args, **kwargs):
        start = time.time()
        model = kwargs.get("model") or (args[0] if args else "unknown")
        messages = kwargs.get("messages", [])

        try:
            response = original_completion(*args, **kwargs)
            latency = (time.time() - start) * 1000

            # LiteLLM returns OpenAI-compatible response
            usage = getattr(response, "usage", None)
            input_tokens = getattr(usage, "prompt_tokens", 0) if usage else 0
            output_tokens = getattr(usage, "completion_tokens", 0) if usage else 0

            completion_text = ""
            choices = getattr(response, "choices", [])
            if choices:
                msg = getattr(choices[0], "message", None)
                if msg:
                    completion_text = getattr(msg, "content", "") or ""

                    tool_calls = getattr(msg, "tool_calls", None)
                    if tool_calls:
                        for tc in tool_calls:
                            fn = getattr(tc, "function", None)
                            if fn:
                                lens.record_tool_call(
                                    tool_name=f"litellm_fn:{getattr(fn, 'name', 'unknown')}",
                                    args=_safe_parse_json(getattr(fn, "arguments", "{}")),
                                    success=True,
                                    duration_ms=0,
                                )

            # Detect provider from model string
            provider = _detect_provider(model)

            lens.record_llm_call(
                model=model,
                prompt=_format_messages(messages),
                completion=completion_text[:2000],
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=latency,
                provider=provider,
            )

            return response

        except Exception as e:
            lens.record_error(e, context=f"LiteLLM {model} call failed")
            raise

    litellm.completion = patched_completion

    # Patch async completion
    original_acompletion = litellm.acompletion

    @functools.wraps(original_acompletion)
    async def patched_acompletion(*args, **kwargs):
        start = time.time()
        model = kwargs.get("model") or (args[0] if args else "unknown")
        messages = kwargs.get("messages", [])

        try:
            response = await original_acompletion(*args, **kwargs)
            latency = (time.time() - start) * 1000

            usage = getattr(response, "usage", None)
            input_tokens = getattr(usage, "prompt_tokens", 0) if usage else 0
            output_tokens = getattr(usage, "completion_tokens", 0) if usage else 0

            completion_text = ""
            choices = getattr(response, "choices", [])
            if choices:
                msg = getattr(choices[0], "message", None)
                if msg:
                    completion_text = getattr(msg, "content", "") or ""

            provider = _detect_provider(model)

            lens.record_llm_call(
                model=model,
                prompt=_format_messages(messages),
                completion=completion_text[:2000],
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=latency,
                provider=provider,
            )

            return response

        except Exception as e:
            lens.record_error(e, context=f"LiteLLM {model} async call failed")
            raise

    litellm.acompletion = patched_acompletion

    # Patch embedding too
    if hasattr(litellm, "embedding"):
        original_embedding = litellm.embedding

        @functools.wraps(original_embedding)
        def patched_embedding(*args, **kwargs):
            start = time.time()
            model = kwargs.get("model") or (args[0] if args else "unknown")

            try:
                response = original_embedding(*args, **kwargs)
                latency = (time.time() - start) * 1000

                usage = getattr(response, "usage", None)
                total_tokens = getattr(usage, "total_tokens", 0) if usage else 0

                lens.record_llm_call(
                    model=model,
                    prompt="[embedding]",
                    completion="[vector]",
                    input_tokens=total_tokens,
                    output_tokens=0,
                    latency_ms=latency,
                    provider=_detect_provider(model),
                )
                return response

            except Exception as e:
                lens.record_error(e, context=f"LiteLLM embedding {model} failed")
                raise

        litellm.embedding = patched_embedding

    if lens.verbose:
        print("[AgentLens] LiteLLM patched — all completion/embedding calls will be tracked")


def _detect_provider(model: str) -> str:
    """Detect provider from LiteLLM model string."""
    m = model.lower()
    if "/" in m:
        return m.split("/")[0]  # e.g., "ollama/llama3" → "ollama"
    if m.startswith("gpt") or m.startswith("o1") or m.startswith("o3"):
        return "openai"
    if "claude" in m:
        return "anthropic"
    if "gemini" in m:
        return "google"
    if "mistral" in m:
        return "mistral"
    if "llama" in m or "codellama" in m:
        return "meta"
    if "command" in m:
        return "cohere"
    return "unknown"


def _format_messages(messages) -> str:
    if not messages:
        return ""
    parts = []
    for msg in messages[:10]:  # Limit to prevent massive prompts
        role = msg.get("role", "")
        content = msg.get("content", "")
        if isinstance(content, list):
            content = " ".join(str(c) for c in content)
        parts.append(f"[{role}] {content}")
    return "\n".join(parts)[:2000]


def _safe_parse_json(s: str) -> dict:
    import json
    try:
        return json.loads(s)
    except Exception:
        return {"raw": s}
