"""
AgentLens OpenAI Integration — auto-patch OpenAI client to capture all LLM calls.

Usage:
    from agentlens.integrations.openai import patch_openai
    patch_openai(lens)  # That's it. All openai calls are now tracked.
"""

import time
import functools
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ..client import AgentLens


def patch_openai(lens: Optional["AgentLens"] = None):
    """Monkey-patch the OpenAI client to auto-record all chat completions.

    Works with both sync and async clients.
    """
    try:
        import openai
    except ImportError:
        raise ImportError("openai package not installed. Run: pip install openai")

    if lens is None:
        from ..client import AgentLens
        lens = AgentLens.get_instance()
        if not lens:
            raise ValueError("No AgentLens instance found. Initialize AgentLens first.")

    # Patch the sync client
    _patch_sync_completions(lens, openai)
    # Patch the async client
    _patch_async_completions(lens, openai)

    if lens.verbose:
        print("[AgentLens] OpenAI patched — all chat.completions calls will be tracked")


def _patch_sync_completions(lens: "AgentLens", openai_module):
    """Patch openai.resources.chat.completions.Completions.create"""
    try:
        from openai.resources.chat import completions as comp_module
        original_create = comp_module.Completions.create

        @functools.wraps(original_create)
        def patched_create(self, *args, **kwargs):
            start = time.time()
            model = kwargs.get("model", "unknown")
            messages = kwargs.get("messages", [])

            try:
                response = original_create(self, *args, **kwargs)
                latency = (time.time() - start) * 1000

                # Extract usage
                usage = getattr(response, "usage", None)
                input_tokens = getattr(usage, "prompt_tokens", 0) if usage else 0
                output_tokens = getattr(usage, "completion_tokens", 0) if usage else 0

                # Extract completion text
                choices = getattr(response, "choices", [])
                completion_text = ""
                if choices:
                    msg = getattr(choices[0], "message", None)
                    if msg:
                        completion_text = getattr(msg, "content", "") or ""

                        # Check for tool calls
                        tool_calls = getattr(msg, "tool_calls", None)
                        if tool_calls:
                            for tc in tool_calls:
                                fn = getattr(tc, "function", None)
                                if fn:
                                    import json
                                    try:
                                        tc_args = json.loads(getattr(fn, "arguments", "{}"))
                                    except Exception:
                                        tc_args = {"raw": getattr(fn, "arguments", "")}
                                    lens.record_tool_call(
                                        tool_name=f"openai_function:{getattr(fn, 'name', 'unknown')}",
                                        args=tc_args,
                                        success=True,
                                        duration_ms=0,
                                    )

                lens.record_llm_call(
                    model=model,
                    prompt=_format_messages(messages),
                    completion=completion_text,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    latency_ms=latency,
                    provider="openai",
                )

                return response

            except Exception as e:
                latency = (time.time() - start) * 1000
                lens.record_error(e, context=f"OpenAI {model} call failed")
                raise

        comp_module.Completions.create = patched_create

    except (ImportError, AttributeError) as e:
        if lens.verbose:
            print(f"[AgentLens] Could not patch sync OpenAI: {e}")


def _patch_async_completions(lens: "AgentLens", openai_module):
    """Patch openai.resources.chat.completions.AsyncCompletions.create"""
    try:
        from openai.resources.chat import completions as comp_module
        original_async_create = comp_module.AsyncCompletions.create

        @functools.wraps(original_async_create)
        async def patched_async_create(self, *args, **kwargs):
            start = time.time()
            model = kwargs.get("model", "unknown")
            messages = kwargs.get("messages", [])

            try:
                response = await original_async_create(self, *args, **kwargs)
                latency = (time.time() - start) * 1000

                usage = getattr(response, "usage", None)
                input_tokens = getattr(usage, "prompt_tokens", 0) if usage else 0
                output_tokens = getattr(usage, "completion_tokens", 0) if usage else 0

                choices = getattr(response, "choices", [])
                completion_text = ""
                if choices:
                    msg = getattr(choices[0], "message", None)
                    if msg:
                        completion_text = getattr(msg, "content", "") or ""

                lens.record_llm_call(
                    model=model,
                    prompt=_format_messages(messages),
                    completion=completion_text,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    latency_ms=latency,
                    provider="openai",
                )

                return response

            except Exception as e:
                lens.record_error(e, context=f"OpenAI async {model} call failed")
                raise

        comp_module.AsyncCompletions.create = patched_async_create

    except (ImportError, AttributeError) as e:
        if lens.verbose:
            print(f"[AgentLens] Could not patch async OpenAI: {e}")


def _format_messages(messages) -> str:
    """Format chat messages list into readable string."""
    if not messages:
        return ""
    parts = []
    for m in messages:
        if isinstance(m, dict):
            role = m.get("role", "?")
            content = m.get("content", "")
        else:
            role = getattr(m, "role", "?")
            content = getattr(m, "content", "")
        if content:
            parts.append(f"[{role}] {content[:500]}")
    return "\n".join(parts)
