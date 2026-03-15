"""
AgentLens Anthropic Integration — auto-patch Anthropic client to capture all Claude calls.

Usage:
    from agentlens.integrations.anthropic import patch_anthropic
    patch_anthropic()  # All anthropic.messages.create() calls are now tracked
"""

import time
import functools
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ..client import AgentLens


def patch_anthropic(lens: Optional["AgentLens"] = None):
    """Monkey-patch the Anthropic client to auto-record all message completions."""
    try:
        import anthropic  # noqa: F401
    except ImportError:
        raise ImportError("anthropic package not installed. Run: pip install anthropic")

    if lens is None:
        from ..client import AgentLens
        lens = AgentLens.get_instance()
        if not lens:
            raise ValueError("No AgentLens instance found. Initialize AgentLens first.")

    _patch_sync_messages(lens)
    _patch_async_messages(lens)

    if lens.verbose:
        print("[AgentLens] Anthropic patched — all messages.create() calls will be tracked")


def _patch_sync_messages(lens: "AgentLens"):
    try:
        from anthropic.resources import messages as msg_module
        original_create = msg_module.Messages.create

        @functools.wraps(original_create)
        def patched_create(self, *args, **kwargs):
            start = time.time()
            model = kwargs.get("model", "unknown")
            messages = kwargs.get("messages", [])
            system = kwargs.get("system", "")

            try:
                response = original_create(self, *args, **kwargs)
                latency = (time.time() - start) * 1000

                # Extract usage
                usage = getattr(response, "usage", None)
                input_tokens = getattr(usage, "input_tokens", 0) if usage else 0
                output_tokens = getattr(usage, "output_tokens", 0) if usage else 0

                # Extract completion text
                content_blocks = getattr(response, "content", [])
                completion_text = ""
                for block in content_blocks:
                    if getattr(block, "type", "") == "text":
                        completion_text += getattr(block, "text", "")

                # Check for tool use blocks
                for block in content_blocks:
                    if getattr(block, "type", "") == "tool_use":
                        lens.record_tool_call(
                            tool_name=f"claude_tool:{getattr(block, 'name', 'unknown')}",
                            args=getattr(block, "input", {}),
                            success=True,
                            duration_ms=0,
                        )

                # Format prompt
                prompt_text = ""
                if system:
                    prompt_text = f"[system] {system}\n"
                for msg in messages:
                    role = msg.get("role", "")
                    content = msg.get("content", "")
                    if isinstance(content, list):
                        content = " ".join(
                            b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
                        )
                    prompt_text += f"[{role}] {content}\n"

                lens.record_llm_call(
                    model=model,
                    prompt=prompt_text[:2000],
                    completion=completion_text[:2000],
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    latency_ms=latency,
                    provider="anthropic",
                )

                return response

            except Exception as e:
                latency = (time.time() - start) * 1000
                lens.record_error(e, context=f"Anthropic {model} call failed")
                raise

        msg_module.Messages.create = patched_create

    except (ImportError, AttributeError) as e:
        if lens.verbose:
            print(f"[AgentLens] Could not patch sync Anthropic: {e}")


def _patch_async_messages(lens: "AgentLens"):
    try:
        from anthropic.resources import messages as msg_module
        original_create = msg_module.AsyncMessages.create

        @functools.wraps(original_create)
        async def patched_create(self, *args, **kwargs):
            start = time.time()
            model = kwargs.get("model", "unknown")
            messages = kwargs.get("messages", [])
            system = kwargs.get("system", "")

            try:
                response = await original_create(self, *args, **kwargs)
                latency = (time.time() - start) * 1000

                usage = getattr(response, "usage", None)
                input_tokens = getattr(usage, "input_tokens", 0) if usage else 0
                output_tokens = getattr(usage, "output_tokens", 0) if usage else 0

                content_blocks = getattr(response, "content", [])
                completion_text = ""
                for block in content_blocks:
                    if getattr(block, "type", "") == "text":
                        completion_text += getattr(block, "text", "")

                for block in content_blocks:
                    if getattr(block, "type", "") == "tool_use":
                        lens.record_tool_call(
                            tool_name=f"claude_tool:{getattr(block, 'name', 'unknown')}",
                            args=getattr(block, "input", {}),
                            success=True,
                            duration_ms=0,
                        )

                prompt_text = ""
                if system:
                    prompt_text = f"[system] {system}\n"
                for msg in messages:
                    role = msg.get("role", "")
                    content = msg.get("content", "")
                    if isinstance(content, list):
                        content = " ".join(
                            b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
                        )
                    prompt_text += f"[{role}] {content}\n"

                lens.record_llm_call(
                    model=model,
                    prompt=prompt_text[:2000],
                    completion=completion_text[:2000],
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    latency_ms=latency,
                    provider="anthropic",
                )

                return response

            except Exception as e:
                lens.record_error(e, context=f"Anthropic {model} call failed")
                raise

        msg_module.AsyncMessages.create = patched_create

    except (ImportError, AttributeError) as e:
        if lens.verbose:
            print(f"[AgentLens] Could not patch async Anthropic: {e}")
