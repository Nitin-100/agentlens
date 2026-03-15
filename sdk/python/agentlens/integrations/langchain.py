"""
AgentLens LangChain Integration — Callback handler for LangChain/LangGraph.

Captures: LLM calls, tool calls, chain runs, agent steps, errors, retries.
Works with LangChain, LangGraph, LangServe — anything using LangChain callbacks.

Usage:
    from agentlens.integrations.langchain import AgentLensCallbackHandler

    handler = AgentLensCallbackHandler()

    # Use with any LangChain component
    llm = ChatOpenAI(model="gpt-4o", callbacks=[handler])
    agent = create_react_agent(llm, tools, callbacks=[handler])
    chain.invoke({"input": "..."}, config={"callbacks": [handler]})
"""

import time
from typing import Any, Dict, List
from uuid import UUID

try:
    from langchain_core.callbacks.base import BaseCallbackHandler
except ImportError:
    try:
        from langchain.callbacks.base import BaseCallbackHandler
    except ImportError:
        # Create a dummy base class so the file can at least be imported
        class BaseCallbackHandler:
            pass


class AgentLensCallbackHandler(BaseCallbackHandler):
    """LangChain callback handler that sends all events to AgentLens."""

    name = "agentlens"

    def __init__(self, lens=None, agent_name: str = "langchain-agent", auto_session: bool = True):
        """
        Args:
            lens: AgentLens instance. If None, uses global instance.
            agent_name: Name for the agent session.
            auto_session: If True, auto-creates a session on first event.
        """
        super().__init__()
        self._lens = lens
        self._agent_name = agent_name
        self._auto_session = auto_session
        self._session_started = False
        self._run_starts: Dict[str, float] = {}  # run_id -> start_time
        self._chain_depth = 0
        self._step_counter = 0

    @property
    def lens(self):
        if self._lens is None:
            from ..client import AgentLens
            self._lens = AgentLens.get_instance()
        return self._lens

    def _ensure_session(self):
        if self._auto_session and not self._session_started and self.lens:
            self.lens.start_session(
                agent_name=self._agent_name,
                tags={"framework": "langchain"},
            )
            self._session_started = True

    def _run_key(self, run_id: UUID) -> str:
        return str(run_id)

    # ─── LLM Events ─────────────────────────────────────────

    def on_llm_start(self, serialized: Dict[str, Any], prompts: List[str],
                     *, run_id: UUID, **kwargs):
        self._ensure_session()
        self._run_starts[self._run_key(run_id)] = time.time()

    def on_chat_model_start(self, serialized: Dict[str, Any], messages: List[List],
                            *, run_id: UUID, **kwargs):
        self._ensure_session()
        self._run_starts[self._run_key(run_id)] = time.time()

    def on_llm_end(self, response, *, run_id: UUID, **kwargs):
        if not self.lens:
            return

        start = self._run_starts.pop(self._run_key(run_id), time.time())
        latency = (time.time() - start) * 1000

        # Extract model info
        model = "unknown"
        llm_output = getattr(response, "llm_output", {}) or {}
        if "model_name" in llm_output:
            model = llm_output["model_name"]
        elif "model" in llm_output:
            model = llm_output["model"]

        # Extract tokens
        token_usage = llm_output.get("token_usage", {}) or {}
        input_tokens = token_usage.get("prompt_tokens", 0)
        output_tokens = token_usage.get("completion_tokens", 0)

        # Extract completion text
        generations = getattr(response, "generations", [[]])
        completion_text = ""
        if generations and generations[0]:
            gen = generations[0][0]
            if hasattr(gen, "message"):
                completion_text = getattr(gen.message, "content", "") or ""
                # Check for tool calls
                tool_calls = getattr(gen.message, "tool_calls", [])
                for tc in (tool_calls or []):
                    self.lens.record_tool_call(
                        tool_name=f"lc_tool_call:{tc.get('name', 'unknown')}",
                        args=tc.get("args", {}),
                        success=True,
                        duration_ms=0,
                    )
            else:
                completion_text = getattr(gen, "text", "") or ""

        self.lens.record_llm_call(
            model=model,
            prompt="[langchain prompt]",
            completion=completion_text[:2000],
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency,
            provider="langchain",
        )

    def on_llm_error(self, error: BaseException, *, run_id: UUID, **kwargs):
        self._run_starts.pop(self._run_key(run_id), None)
        if self.lens:
            self.lens.record_error(
                error if isinstance(error, Exception) else Exception(str(error)),
                context="LangChain LLM call failed",
            )

    # ─── Tool Events ────────────────────────────────────────

    def on_tool_start(self, serialized: Dict[str, Any], input_str: str,
                      *, run_id: UUID, **kwargs):
        self._ensure_session()
        self._run_starts[self._run_key(run_id)] = time.time()

    def on_tool_end(self, output: str, *, run_id: UUID, **kwargs):
        if not self.lens:
            return

        start = self._run_starts.pop(self._run_key(run_id), time.time())
        duration = (time.time() - start) * 1000

        tool_name = kwargs.get("name", "unknown_tool")

        self.lens.record_tool_call(
            tool_name=tool_name,
            result=str(output)[:500],
            duration_ms=duration,
            success=True,
        )

    def on_tool_error(self, error: BaseException, *, run_id: UUID, **kwargs):
        if not self.lens:
            return

        start = self._run_starts.pop(self._run_key(run_id), time.time())
        duration = (time.time() - start) * 1000

        tool_name = kwargs.get("name", "unknown_tool")

        self.lens.record_tool_call(
            tool_name=tool_name,
            duration_ms=duration,
            success=False,
            error=str(error),
        )

    # ─── Chain Events ────────────────────────────────────────

    def on_chain_start(self, serialized: Dict[str, Any], inputs: Dict[str, Any],
                       *, run_id: UUID, **kwargs):
        self._ensure_session()
        self._chain_depth += 1
        self._run_starts[self._run_key(run_id)] = time.time()

        if self.lens and self._chain_depth == 1:
            self._step_counter += 1
            chain_name = serialized.get("name", serialized.get("id", ["unknown"])[-1] if isinstance(serialized.get("id"), list) else "unknown")
            self.lens.record_step(
                step_number=self._step_counter,
                thought=f"Starting chain: {chain_name}",
                decision=chain_name,
            )

    def on_chain_end(self, outputs: Dict[str, Any], *, run_id: UUID, **kwargs):
        self._chain_depth = max(0, self._chain_depth - 1)
        self._run_starts.pop(self._run_key(run_id), None)

    def on_chain_error(self, error: BaseException, *, run_id: UUID, **kwargs):
        self._chain_depth = max(0, self._chain_depth - 1)
        self._run_starts.pop(self._run_key(run_id), None)
        if self.lens:
            self.lens.record_error(
                error if isinstance(error, Exception) else Exception(str(error)),
                context="LangChain chain failed",
            )

    # ─── Agent Events ────────────────────────────────────────

    def on_agent_action(self, action, *, run_id: UUID, **kwargs):
        if self.lens:
            self._step_counter += 1
            tool_name = getattr(action, "tool", "unknown")
            getattr(action, "tool_input", "")
            self.lens.record_step(
                step_number=self._step_counter,
                thought=f"Agent decided to use tool: {tool_name}",
                decision=f"call:{tool_name}",
            )

    def on_agent_finish(self, finish, *, run_id: UUID, **kwargs):
        if self.lens and self._session_started:
            output = getattr(finish, "return_values", {})
            self.lens.end_session(
                success=True,
                output_data=str(output)[:1000],
            )
            self._session_started = False

    # ─── Retry Events ────────────────────────────────────────

    def on_retry(self, retry_state, *, run_id: UUID, **kwargs):
        if self.lens:
            self.lens.record_custom(
                "retry",
                data={
                    "attempt": getattr(retry_state, "attempt_number", 0),
                    "outcome": str(getattr(retry_state, "outcome", ""))[:200],
                },
            )
