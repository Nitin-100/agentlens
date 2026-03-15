"""
AgentLens — AI Agent Observability SDK
Monitor what your AI agents actually do.
Works with ANY agent framework: OpenAI, Claude, Gemini, LangChain, CrewAI, Google ADK, LiteLLM, or custom.

Usage:
    from agentlens import AgentLens, monitor, auto_patch

    lens = AgentLens(server_url="http://localhost:8340")
    auto_patch()  # auto-detects and patches all installed frameworks

    @monitor("my-agent")
    def my_agent(task):
        # your agent code — all LLM calls, tools, errors auto-captured
        pass

Framework-specific:
    from agentlens.integrations.openai import patch_openai
    from agentlens.integrations.anthropic import patch_anthropic
    from agentlens.integrations.google_adk import patch_gemini, patch_google_adk
    from agentlens.integrations.litellm import patch_litellm
    from agentlens.integrations.crewai import patch_crewai
    from agentlens.integrations.langchain import AgentLensCallbackHandler
"""

__version__ = "0.3.0"

from .client import AgentLens
from .decorators import monitor, tool, step
from .events import Event, EventType
from .integrations.auto import auto_patch
from .plugins import PluginRegistry, DatabasePlugin, ExporterPlugin, EventProcessor

__all__ = [
    "AgentLens", "monitor", "tool", "step", "Event", "EventType", "auto_patch",
    "PluginRegistry", "DatabasePlugin", "ExporterPlugin", "EventProcessor",
]
