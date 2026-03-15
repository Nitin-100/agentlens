"""
AgentLens Decorators — @monitor, @tool, @step
Zero-friction way to instrument agent code.
"""

import time
import functools
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .client import AgentLens


def _make_monitor(lens: "AgentLens", agent_name: str, tags: Optional[dict] = None):
    """Create a monitor decorator bound to a specific AgentLens instance."""

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            session = lens.start_session(
                agent_name=agent_name,
                tags=tags or {},
                input_data={"args": str(args)[:500], "kwargs": str(kwargs)[:500]},
            )
            try:
                result = func(*args, **kwargs)
                lens.end_session(
                    session_id=session.session_id,
                    success=True,
                    output_data=str(result)[:1000] if result else None,
                )
                return result
            except Exception as e:
                lens.record_error(e, context=f"Agent {agent_name} crashed")
                lens.end_session(
                    session_id=session.session_id,
                    success=False,
                    output_data=str(e),
                )
                raise

        # Async variant
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            session = lens.start_session(
                agent_name=agent_name,
                tags=tags or {},
                input_data={"args": str(args)[:500], "kwargs": str(kwargs)[:500]},
            )
            try:
                result = await func(*args, **kwargs)
                lens.end_session(
                    session_id=session.session_id,
                    success=True,
                    output_data=str(result)[:1000] if result else None,
                )
                return result
            except Exception as e:
                lens.record_error(e, context=f"Agent {agent_name} crashed")
                lens.end_session(
                    session_id=session.session_id,
                    success=False,
                    output_data=str(e),
                )
                raise

        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return wrapper

    return decorator


def monitor(agent_name: str = "default", tags: Optional[dict] = None):
    """Standalone decorator — uses the global AgentLens instance.

    Usage:
        from agentlens import monitor

        @monitor("my-agent")
        def run_agent():
            ...
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            from .client import AgentLens

            lens = AgentLens.get_instance()
            if not lens:
                # No client initialized — run without monitoring
                return func(*args, **kwargs)
            wrapped = _make_monitor(lens, agent_name, tags)(func)
            return wrapped(*args, **kwargs)

        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            from .client import AgentLens

            lens = AgentLens.get_instance()
            if not lens:
                return await func(*args, **kwargs)
            wrapped = _make_monitor(lens, agent_name, tags)(func)
            return await wrapped(*args, **kwargs)

        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return wrapper

    return decorator


def tool(name: Optional[str] = None, tags: Optional[dict] = None):
    """Decorator to track tool/function calls.

    Usage:
        @tool("web-search")
        def search_web(query):
            ...
    """

    def decorator(func):
        tool_name = name or func.__name__

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            from .client import AgentLens

            lens = AgentLens.get_instance()
            start = time.time()

            try:
                result = func(*args, **kwargs)
                elapsed = (time.time() - start) * 1000

                if lens:
                    lens.record_tool_call(
                        tool_name=tool_name,
                        args=kwargs if kwargs else {"args": str(args)[:200]},
                        result=result,
                        duration_ms=elapsed,
                        success=True,
                        tags=tags or {},
                    )
                return result
            except Exception as e:
                elapsed = (time.time() - start) * 1000
                if lens:
                    lens.record_tool_call(
                        tool_name=tool_name,
                        args=kwargs if kwargs else {"args": str(args)[:200]},
                        duration_ms=elapsed,
                        success=False,
                        error=str(e),
                        tags=tags or {},
                    )
                raise

        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            from .client import AgentLens

            lens = AgentLens.get_instance()
            start = time.time()

            try:
                result = await func(*args, **kwargs)
                elapsed = (time.time() - start) * 1000

                if lens:
                    lens.record_tool_call(
                        tool_name=tool_name,
                        args=kwargs if kwargs else {"args": str(args)[:200]},
                        result=result,
                        duration_ms=elapsed,
                        success=True,
                        tags=tags or {},
                    )
                return result
            except Exception as e:
                elapsed = (time.time() - start) * 1000
                if lens:
                    lens.record_tool_call(
                        tool_name=tool_name,
                        args=kwargs if kwargs else {"args": str(args)[:200]},
                        duration_ms=elapsed,
                        success=False,
                        error=str(e),
                        tags=tags or {},
                    )
                raise

        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return wrapper

    return decorator


def step(step_name: Optional[str] = None):
    """Decorator to mark a function as an agent step.

    Usage:
        @step("analyze-input")
        def analyze(data):
            ...
    """

    _step_counter = {"count": 0}

    def decorator(func):
        name = step_name or func.__name__

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            from .client import AgentLens

            lens = AgentLens.get_instance()
            _step_counter["count"] += 1

            if lens:
                lens.record_step(
                    step_number=_step_counter["count"],
                    thought=f"Executing step: {name}",
                    decision=name,
                )

            return func(*args, **kwargs)

        return wrapper

    return decorator
