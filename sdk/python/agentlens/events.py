"""
AgentLens Event Types — what gets captured from agent activity.
"""

import time
import uuid
from enum import Enum
from dataclasses import dataclass, field, asdict
from typing import Any, Optional


class EventType(str, Enum):
    # Agent lifecycle
    SESSION_START = "session.start"
    SESSION_END = "session.end"

    # LLM calls
    LLM_REQUEST = "llm.request"
    LLM_RESPONSE = "llm.response"
    LLM_ERROR = "llm.error"

    # Tool / function calls
    TOOL_CALL = "tool.call"
    TOOL_RESULT = "tool.result"
    TOOL_ERROR = "tool.error"

    # Agent decisions
    AGENT_STEP = "agent.step"
    AGENT_DECISION = "agent.decision"
    AGENT_THOUGHT = "agent.thought"

    # Custom
    CUSTOM = "custom"

    # Errors
    ERROR = "error"
    GUARDRAIL_TRIGGERED = "guardrail.triggered"


# Known model costs (per 1K tokens) as of March 2026
MODEL_COSTS = {
    # OpenAI
    "gpt-4o": {"input": 0.0025, "output": 0.01},
    "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
    "gpt-4-turbo": {"input": 0.01, "output": 0.03},
    "gpt-4": {"input": 0.03, "output": 0.06},
    "gpt-3.5-turbo": {"input": 0.0005, "output": 0.0015},
    "o1": {"input": 0.015, "output": 0.06},
    "o1-mini": {"input": 0.003, "output": 0.012},
    "o3-mini": {"input": 0.0011, "output": 0.0044},

    # Anthropic
    "claude-3-opus": {"input": 0.015, "output": 0.075},
    "claude-3-sonnet": {"input": 0.003, "output": 0.015},
    "claude-3-haiku": {"input": 0.00025, "output": 0.00125},
    "claude-3.5-sonnet": {"input": 0.003, "output": 0.015},
    "claude-4-opus": {"input": 0.015, "output": 0.075},
    "claude-4-sonnet": {"input": 0.003, "output": 0.015},

    # Google
    "gemini-pro": {"input": 0.00025, "output": 0.0005},
    "gemini-1.5-pro": {"input": 0.00125, "output": 0.005},
    "gemini-1.5-flash": {"input": 0.000075, "output": 0.0003},

    # Mistral
    "mistral-large": {"input": 0.004, "output": 0.012},
    "mistral-small": {"input": 0.001, "output": 0.003},

    # Open / local (free)
    "llama-3": {"input": 0, "output": 0},
    "llama-3.1": {"input": 0, "output": 0},
    "mistral": {"input": 0, "output": 0},
    "phi-3": {"input": 0, "output": 0},
    "qwen": {"input": 0, "output": 0},
}


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate cost in USD for a given model and token counts."""
    model_lower = model.lower()
    for name, costs in MODEL_COSTS.items():
        if name in model_lower:
            return (input_tokens / 1000 * costs["input"]) + (
                output_tokens / 1000 * costs["output"]
            )
    return 0.0  # Unknown model


@dataclass
class Event:
    """A single observable event from an agent's execution."""

    event_type: EventType
    timestamp: float = field(default_factory=time.time)
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str = ""
    agent_name: str = ""
    project_id: str = ""

    # LLM-specific
    model: Optional[str] = None
    provider: Optional[str] = None
    prompt: Optional[str] = None
    completion: Optional[str] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    cost_usd: Optional[float] = None
    latency_ms: Optional[float] = None

    # Tool-specific
    tool_name: Optional[str] = None
    tool_args: Optional[dict] = None
    tool_result: Optional[Any] = None

    # Agent decision
    thought: Optional[str] = None
    decision: Optional[str] = None
    step_number: Optional[int] = None

    # User tracking
    user_id: Optional[str] = None

    # Error
    error_message: Optional[str] = None
    error_type: Optional[str] = None
    stack_trace: Optional[str] = None

    # Tags and metadata
    tags: dict = field(default_factory=dict)
    meta: dict = field(default_factory=dict)

    # Status
    success: Optional[bool] = None
    duration_ms: Optional[float] = None

    # Parent event (for nesting)
    parent_id: Optional[str] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["event_type"] = self.event_type.value
        # Remove None values to save bandwidth
        return {k: v for k, v in d.items() if v is not None}

    def compute_cost(self):
        """Auto-compute cost if model and tokens are available."""
        if self.model and self.input_tokens is not None and self.output_tokens is not None:
            self.cost_usd = estimate_cost(
                self.model, self.input_tokens, self.output_tokens
            )


@dataclass
class Session:
    """An agent execution session — one run of an agent."""

    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    agent_name: str = ""
    project_id: str = ""
    started_at: float = field(default_factory=time.time)
    ended_at: Optional[float] = None
    success: Optional[bool] = None
    total_cost_usd: float = 0.0
    total_tokens: int = 0
    total_llm_calls: int = 0
    total_tool_calls: int = 0
    total_steps: int = 0
    error_count: int = 0
    events: list = field(default_factory=list)
    tags: dict = field(default_factory=dict)
    input_data: Optional[Any] = None
    output_data: Optional[Any] = None
    user_id: Optional[str] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["events"] = [e if isinstance(e, dict) else e.to_dict() for e in self.events]
        return {k: v for k, v in d.items() if v is not None}
