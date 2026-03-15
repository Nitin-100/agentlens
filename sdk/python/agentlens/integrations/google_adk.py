"""
AgentLens Google ADK Integration — hook into Google's Agent Development Kit.

Works with google-adk agents by patching the Runner and LLM calls.

Usage:
    from agentlens.integrations.google_adk import patch_google_adk
    patch_google_adk()

Also works with raw google.generativeai (Gemini):
    from agentlens.integrations.google_adk import patch_gemini
    patch_gemini()
"""

import time
import functools
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ..client import AgentLens


def patch_gemini(lens: Optional["AgentLens"] = None):
    """Patch google.generativeai to auto-capture all Gemini generate_content calls."""
    try:
        import google.generativeai as genai
    except ImportError:
        raise ImportError("google-generativeai not installed. Run: pip install google-generativeai")

    if lens is None:
        from ..client import AgentLens
        lens = AgentLens.get_instance()
        if not lens:
            raise ValueError("No AgentLens instance found. Initialize AgentLens first.")

    # Patch GenerativeModel.generate_content
    original_generate = genai.GenerativeModel.generate_content

    @functools.wraps(original_generate)
    def patched_generate(self, *args, **kwargs):
        start = time.time()
        model_name = getattr(self, "model_name", "gemini-unknown")

        # Extract prompt
        contents = args[0] if args else kwargs.get("contents", "")
        prompt_text = _extract_gemini_prompt(contents)

        try:
            response = original_generate(self, *args, **kwargs)
            latency = (time.time() - start) * 1000

            # Extract response text
            completion_text = ""
            try:
                completion_text = response.text
            except Exception:
                try:
                    for part in response.parts:
                        completion_text += getattr(part, "text", "")
                except Exception:
                    completion_text = str(response)[:500]

            # Extract usage metadata
            usage = getattr(response, "usage_metadata", None)
            input_tokens = getattr(usage, "prompt_token_count", 0) if usage else 0
            output_tokens = getattr(usage, "candidates_token_count", 0) if usage else 0

            # Check for function calls
            try:
                for part in response.parts:
                    fc = getattr(part, "function_call", None)
                    if fc:
                        lens.record_tool_call(
                            tool_name=f"gemini_fn:{getattr(fc, 'name', 'unknown')}",
                            args=dict(fc.args) if hasattr(fc, "args") else {},
                            success=True,
                            duration_ms=0,
                        )
            except Exception:
                pass

            lens.record_llm_call(
                model=model_name,
                prompt=prompt_text[:2000],
                completion=completion_text[:2000],
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=latency,
                provider="google",
            )

            return response

        except Exception as e:
            lens.record_error(e, context=f"Gemini {model_name} call failed")
            raise

    genai.GenerativeModel.generate_content = patched_generate

    # Also patch async if available
    if hasattr(genai.GenerativeModel, "generate_content_async"):
        original_async = genai.GenerativeModel.generate_content_async

        @functools.wraps(original_async)
        async def patched_async_generate(self, *args, **kwargs):
            start = time.time()
            model_name = getattr(self, "model_name", "gemini-unknown")
            contents = args[0] if args else kwargs.get("contents", "")
            prompt_text = _extract_gemini_prompt(contents)

            try:
                response = await original_async(self, *args, **kwargs)
                latency = (time.time() - start) * 1000

                completion_text = ""
                try:
                    completion_text = response.text
                except Exception:
                    completion_text = str(response)[:500]

                usage = getattr(response, "usage_metadata", None)
                input_tokens = getattr(usage, "prompt_token_count", 0) if usage else 0
                output_tokens = getattr(usage, "candidates_token_count", 0) if usage else 0

                lens.record_llm_call(
                    model=model_name,
                    prompt=prompt_text[:2000],
                    completion=completion_text[:2000],
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    latency_ms=latency,
                    provider="google",
                )

                return response

            except Exception as e:
                lens.record_error(e, context=f"Gemini {model_name} async call failed")
                raise

        genai.GenerativeModel.generate_content_async = patched_async_generate

    if lens.verbose:
        print("[AgentLens] Google Gemini patched — all generate_content() calls will be tracked")


def patch_google_adk(lens: Optional["AgentLens"] = None):
    """Patch Google ADK Runner to auto-capture agent sessions and tool calls.

    Works with:
        from google.adk import Agent, Runner
        agent = Agent(name="my-agent", model="gemini-2.0-flash", tools=[...])
        runner = Runner(agent=agent)
    """
    if lens is None:
        from ..client import AgentLens
        lens = AgentLens.get_instance()
        if not lens:
            raise ValueError("No AgentLens instance found.")

    # Patch Gemini calls first
    try:
        patch_gemini(lens)
    except ImportError:
        pass

    # Patch google.adk.Runner.run
    try:
        from google.adk.runners import Runner
        original_run = Runner.run

        @functools.wraps(original_run)
        async def patched_run(self, *args, **kwargs):
            agent_name = "google-adk-agent"
            try:
                agent_name = getattr(self, "agent", None)
                if agent_name:
                    agent_name = getattr(agent_name, "name", "google-adk-agent")
            except Exception:
                pass

            session = lens.start_session(
                agent_name=agent_name,
                tags={"framework": "google-adk"},
                input_data=str(args)[:500],
            )

            try:
                result = await original_run(self, *args, **kwargs)
                lens.end_session(session_id=session.session_id, success=True, output_data=str(result)[:1000])
                return result
            except Exception as e:
                lens.record_error(e, context=f"Google ADK agent '{agent_name}' failed")
                lens.end_session(session_id=session.session_id, success=False, output_data=str(e))
                raise

        Runner.run = patched_run

        if lens.verbose:
            print("[AgentLens] Google ADK Runner patched — agent runs will be tracked")

    except ImportError:
        if lens and lens.verbose:
            print("[AgentLens] google-adk not installed. Only Gemini calls will be patched.")


def _extract_gemini_prompt(contents) -> str:
    """Extract text from various Gemini content formats."""
    if isinstance(contents, str):
        return contents
    if isinstance(contents, list):
        parts = []
        for item in contents:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                role = item.get("role", "")
                text = item.get("parts", [])
                if isinstance(text, list):
                    text = " ".join(str(p) for p in text)
                parts.append(f"[{role}] {text}")
            else:
                parts.append(str(item)[:200])
        return "\n".join(parts)
    return str(contents)[:500]
