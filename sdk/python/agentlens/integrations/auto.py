"""
AgentLens Generic Auto-Patcher — automatically detect and patch whatever LLM/agent
framework is installed. One function to rule them all.

Usage:
    from agentlens.integrations.auto import auto_patch
    auto_patch()  # Detects and patches everything installed

This will automatically detect and patch:
    - OpenAI (openai)
    - Anthropic (anthropic)
    - Google Gemini (google-generativeai)
    - Google ADK (google-adk)
    - LiteLLM (litellm)
    - LangChain (langchain / langchain-core)
    - CrewAI (crewai)
"""

from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ..client import AgentLens


def auto_patch(lens: Optional["AgentLens"] = None, verbose: bool = True):
    """Auto-detect installed frameworks and patch them all.

    Returns a dict of what was patched and what wasn't.
    """
    if lens is None:
        from ..client import AgentLens
        lens = AgentLens.get_instance()
        if not lens:
            raise ValueError("No AgentLens instance found. Initialize AgentLens first.")

    results = {}

    # OpenAI
    try:
        from .openai import patch_openai
        patch_openai(lens)
        results["openai"] = "patched"
    except ImportError:
        results["openai"] = "not installed"
    except Exception as e:
        results["openai"] = f"error: {e}"

    # Anthropic
    try:
        from .anthropic import patch_anthropic
        patch_anthropic(lens)
        results["anthropic"] = "patched"
    except ImportError:
        results["anthropic"] = "not installed"
    except Exception as e:
        results["anthropic"] = f"error: {e}"

    # Google Gemini
    try:
        from .google_adk import patch_gemini
        patch_gemini(lens)
        results["google-gemini"] = "patched"
    except ImportError:
        results["google-gemini"] = "not installed"
    except Exception as e:
        results["google-gemini"] = f"error: {e}"

    # Google ADK
    try:
        from .google_adk import patch_google_adk
        patch_google_adk(lens)
        results["google-adk"] = "patched"
    except ImportError:
        results["google-adk"] = "not installed"
    except Exception as e:
        results["google-adk"] = f"error: {e}"

    # LiteLLM (universal — patches 100+ providers)
    try:
        from .litellm import patch_litellm
        patch_litellm(lens)
        results["litellm"] = "patched"
    except ImportError:
        results["litellm"] = "not installed"
    except Exception as e:
        results["litellm"] = f"error: {e}"

    # CrewAI
    try:
        from .crewai import patch_crewai
        patch_crewai(lens)
        results["crewai"] = "patched"
    except ImportError:
        results["crewai"] = "not installed"
    except Exception as e:
        results["crewai"] = f"error: {e}"

    # LangChain — callback handler, not monkey-patched
    try:
        from .langchain import AgentLensCallbackHandler
        results["langchain"] = "available (use AgentLensCallbackHandler)"
    except ImportError:
        results["langchain"] = "not installed"

    if verbose:
        print("[AgentLens] Auto-patch results:")
        for framework, status in results.items():
            icon = "✅" if "patched" in status else "⬚" if "not installed" in status else "⚠️"
            print(f"  {icon} {framework}: {status}")

    return results
