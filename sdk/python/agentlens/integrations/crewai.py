"""
AgentLens CrewAI Integration — hook into CrewAI's agent/task execution.

Usage:
    from agentlens.integrations.crewai import patch_crewai
    patch_crewai()

    # Now all CrewAI Crew kicks, agent executions, and task runs are tracked
    crew = Crew(agents=[...], tasks=[...])
    crew.kickoff()  # ← auto-tracked
"""

import time
import functools
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ..client import AgentLens


def patch_crewai(lens: Optional["AgentLens"] = None):
    """Patch CrewAI to auto-capture crew kicks, agent executions, and task runs."""
    try:
        import crewai
    except ImportError:
        raise ImportError("crewai not installed. Run: pip install crewai")

    if lens is None:
        from ..client import AgentLens
        lens = AgentLens.get_instance()
        if not lens:
            raise ValueError("No AgentLens instance found.")

    _patch_crew_kickoff(lens, crewai)
    _patch_agent_execute(lens, crewai)
    _patch_task_execute(lens, crewai)

    if lens.verbose:
        print("[AgentLens] CrewAI patched — crews, agents, and tasks will be tracked")


def _patch_crew_kickoff(lens: "AgentLens", crewai_module):
    """Patch Crew.kickoff() to create a session per crew run."""
    try:
        from crewai import Crew
        original_kickoff = Crew.kickoff

        @functools.wraps(original_kickoff)
        def patched_kickoff(self, *args, **kwargs):
            crew_name = getattr(self, "name", None) or "crewai-crew"
            agent_names = []
            try:
                for agent in (getattr(self, "agents", []) or []):
                    agent_names.append(getattr(agent, "role", "unknown"))
            except Exception:
                pass

            session = lens.start_session(
                agent_name=crew_name,
                tags={
                    "framework": "crewai",
                    "type": "crew",
                    "agents": agent_names,
                },
            )

            try:
                result = original_kickoff(self, *args, **kwargs)
                lens.end_session(
                    session_id=session.session_id,
                    success=True,
                    output_data=str(result)[:1000],
                )
                return result
            except Exception as e:
                lens.record_error(e, context=f"CrewAI crew '{crew_name}' failed")
                lens.end_session(
                    session_id=session.session_id,
                    success=False,
                    output_data=str(e),
                )
                raise

        Crew.kickoff = patched_kickoff

        # Also patch async kickoff
        if hasattr(Crew, "kickoff_async"):
            original_async = Crew.kickoff_async

            @functools.wraps(original_async)
            async def patched_async_kickoff(self, *args, **kwargs):
                crew_name = getattr(self, "name", None) or "crewai-crew"
                session = lens.start_session(
                    agent_name=crew_name,
                    tags={"framework": "crewai", "type": "crew"},
                )
                try:
                    result = await original_async(self, *args, **kwargs)
                    lens.end_session(session_id=session.session_id, success=True, output_data=str(result)[:1000])
                    return result
                except Exception as e:
                    lens.record_error(e, context=f"CrewAI crew '{crew_name}' async failed")
                    lens.end_session(session_id=session.session_id, success=False, output_data=str(e))
                    raise

            Crew.kickoff_async = patched_async_kickoff

    except (ImportError, AttributeError) as e:
        if lens.verbose:
            print(f"[AgentLens] Could not patch Crew.kickoff: {e}")


def _patch_agent_execute(lens: "AgentLens", crewai_module):
    """Patch CrewAI Agent.execute_task() to track individual agent executions."""
    try:
        from crewai import Agent
        original_execute = Agent.execute_task

        @functools.wraps(original_execute)
        def patched_execute(self, *args, **kwargs):
            role = getattr(self, "role", "unknown-agent")
            start = time.time()

            lens.record_step(
                step_number=0,
                thought=f"Agent '{role}' executing task",
                decision=f"agent:{role}",
            )

            try:
                result = original_execute(self, *args, **kwargs)
                elapsed = (time.time() - start) * 1000

                lens.record_tool_call(
                    tool_name=f"crewai_agent:{role}",
                    result=str(result)[:500],
                    duration_ms=elapsed,
                    success=True,
                    tags={"framework": "crewai", "type": "agent_execution"},
                )
                return result
            except Exception as e:
                elapsed = (time.time() - start) * 1000
                lens.record_tool_call(
                    tool_name=f"crewai_agent:{role}",
                    duration_ms=elapsed,
                    success=False,
                    error=str(e),
                    tags={"framework": "crewai"},
                )
                raise

        Agent.execute_task = patched_execute

    except (ImportError, AttributeError) as e:
        if lens.verbose:
            print(f"[AgentLens] Could not patch Agent.execute_task: {e}")


def _patch_task_execute(lens: "AgentLens", crewai_module):
    """Patch CrewAI Task.execute() to track individual task runs."""
    try:
        from crewai import Task
        original_execute = Task.execute_sync

        @functools.wraps(original_execute)
        def patched_execute(self, *args, **kwargs):
            task_desc = getattr(self, "description", "unknown task")[:100]
            start = time.time()

            lens.record_step(
                step_number=0,
                thought=f"Executing task: {task_desc}",
                decision="task",
            )

            try:
                result = original_execute(self, *args, **kwargs)
                elapsed = (time.time() - start) * 1000

                lens.record_tool_call(
                    tool_name="crewai_task",
                    args={"description": task_desc},
                    result=str(result)[:500],
                    duration_ms=elapsed,
                    success=True,
                    tags={"framework": "crewai", "type": "task"},
                )
                return result
            except Exception as e:
                elapsed = (time.time() - start) * 1000
                lens.record_tool_call(
                    tool_name="crewai_task",
                    args={"description": task_desc},
                    duration_ms=elapsed,
                    success=False,
                    error=str(e),
                    tags={"framework": "crewai", "type": "task"},
                )
                raise

        Task.execute_sync = patched_execute

    except (ImportError, AttributeError) as e:
        if lens.verbose:
            print(f"[AgentLens] Could not patch Task.execute_sync: {e}")
