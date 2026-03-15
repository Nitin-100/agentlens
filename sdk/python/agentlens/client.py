"""
AgentLens Client — the core connection to the AgentLens server.
Handles event batching, flushing, session management, retries,
circuit breaking, dead letter queue, and graceful shutdown.

Production-grade features:
  - Exponential backoff retry (configurable max_retries, base_delay)
  - Circuit breaker (open after N consecutive failures, half-open probe)
  - Dead Letter Queue (persist failed events to disk, auto-replay)
  - Graceful shutdown with drain timeout
  - Configurable sampling rate
  - On-failure callback hooks
  - Thread-safe everything
"""

import os
import time
import json
import atexit
import threading
from typing import Optional, Any, Callable
from urllib.request import Request, urlopen
from urllib.error import URLError

from .events import Event, EventType, Session


# ─── Circuit Breaker ─────────────────────────────────────────
class CircuitBreaker:
    """Prevents hammering a dead server. Three states: CLOSED → OPEN → HALF_OPEN."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 30.0):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.state = self.CLOSED
        self.failure_count = 0
        self.last_failure_time: float = 0
        self._lock = threading.Lock()

    def record_success(self):
        with self._lock:
            self.failure_count = 0
            self.state = self.CLOSED

    def record_failure(self):
        with self._lock:
            self.failure_count += 1
            self.last_failure_time = time.time()
            if self.failure_count >= self.failure_threshold:
                self.state = self.OPEN

    def can_execute(self) -> bool:
        with self._lock:
            if self.state == self.CLOSED:
                return True
            if self.state == self.OPEN:
                # Check if recovery timeout elapsed → transition to half-open
                if time.time() - self.last_failure_time >= self.recovery_timeout:
                    self.state = self.HALF_OPEN
                    return True
                return False
            # HALF_OPEN — allow one probe request
            return True


class AgentLens:
    """Main client. Initialize once, use everywhere.

    Usage:
        lens = AgentLens(
            api_key="al_xxxxxxxx",
            project="my-project",
            server_url="http://localhost:8340",  # self-hosted
            max_retries=3,
            sample_rate=1.0,                     # 1.0 = capture everything
            on_error=my_error_callback,          # optional failure hook
            dlq_path="./agentlens_dlq.jsonl",    # dead letter queue file
        )
    """

    _instance = None  # Singleton for global access

    def __init__(
        self,
        api_key: str = "",
        project: str = "default",
        server_url: str = "http://localhost:8340",
        flush_interval: float = 2.0,
        batch_size: int = 50,
        max_retries: int = 3,
        retry_base_delay: float = 1.0,
        enabled: bool = True,
        verbose: bool = False,
        sample_rate: float = 1.0,
        on_error: Optional[Callable] = None,
        on_flush_failure: Optional[Callable] = None,
        dlq_path: Optional[str] = None,
        drain_timeout: float = 5.0,
        circuit_failure_threshold: int = 5,
        circuit_recovery_timeout: float = 30.0,
        max_buffer_size: int = 10000,
    ):
        self.api_key = api_key
        self.project = project
        self.server_url = server_url.rstrip("/")
        self.flush_interval = flush_interval
        self.batch_size = batch_size
        self.max_retries = max_retries
        self.retry_base_delay = retry_base_delay
        self.enabled = enabled
        self.verbose = verbose
        self.sample_rate = max(0.0, min(1.0, sample_rate))
        self.on_error = on_error
        self.on_flush_failure = on_flush_failure
        self.dlq_path = dlq_path or os.path.join(os.getcwd(), "agentlens_dlq.jsonl")
        self.drain_timeout = drain_timeout
        self.max_buffer_size = max_buffer_size

        self._buffer: list[dict] = []
        self._lock = threading.Lock()
        self._active_sessions: dict[str, Session] = {}
        self._current_session_id: Optional[str] = None
        self._current_user_id: Optional[str] = None
        self._global_metadata: dict = {}
        self._shutting_down = False
        self._flush_event = threading.Event()
        self._total_events_sent = 0
        self._total_events_dropped = 0
        self._total_flush_failures = 0

        # Circuit breaker
        self._circuit = CircuitBreaker(
            failure_threshold=circuit_failure_threshold,
            recovery_timeout=circuit_recovery_timeout,
        )

        # Set as global instance
        AgentLens._instance = self

        # Start background flush thread
        if enabled:
            self._flush_thread = threading.Thread(
                target=self._flush_loop, daemon=True, name="agentlens-flush"
            )
            self._flush_thread.start()
            atexit.register(self.shutdown)

            # Try to replay DLQ on startup
            self._replay_dlq()

    @classmethod
    def get_instance(cls) -> Optional["AgentLens"]:
        return cls._instance

    # ─── User & Metadata ─────────────────────────────────────
    def set_user(self, user_id: str):
        """Set the current user ID. All subsequent events will be tagged with this user."""
        self._current_user_id = user_id

    def get_user(self) -> Optional[str]:
        return self._current_user_id

    def clear_user(self):
        self._current_user_id = None

    def set_metadata(self, **kwargs):
        """Set global metadata added to every event. e.g. lens.set_metadata(environment='prod', version='1.2')"""
        self._global_metadata.update(kwargs)

    # ─── Session Management ──────────────────────────────────
    def start_session(
        self,
        agent_name: str = "default",
        tags: Optional[dict] = None,
        input_data: Any = None,
        user_id: Optional[str] = None,
    ) -> Session:
        effective_user = user_id or self._current_user_id
        session = Session(
            agent_name=agent_name,
            project_id=self.project,
            tags=tags or {},
            input_data=input_data,
            user_id=effective_user,
        )
        self._active_sessions[session.session_id] = session
        self._current_session_id = session.session_id

        self._record(Event(
            event_type=EventType.SESSION_START,
            session_id=session.session_id,
            agent_name=agent_name,
            project_id=self.project,
            tags=tags or {},
            user_id=effective_user,
        ))

        if self.verbose:
            print(f"[AgentLens] Session started: {session.session_id[:8]}... ({agent_name})")

        return session

    def end_session(
        self,
        session_id: Optional[str] = None,
        success: bool = True,
        output_data: Any = None,
    ):
        sid = session_id or self._current_session_id
        if not sid or sid not in self._active_sessions:
            return

        session = self._active_sessions[sid]
        session.ended_at = time.time()
        session.success = success
        session.output_data = output_data

        self._record(Event(
            event_type=EventType.SESSION_END,
            session_id=sid,
            agent_name=session.agent_name,
            project_id=self.project,
            success=success,
            duration_ms=(session.ended_at - session.started_at) * 1000,
            meta={
                "total_cost": session.total_cost_usd,
                "total_tokens": session.total_tokens,
                "llm_calls": session.total_llm_calls,
                "tool_calls": session.total_tool_calls,
                "steps": session.total_steps,
                "errors": session.error_count,
            },
        ))

        del self._active_sessions[sid]
        if self._current_session_id == sid:
            self._current_session_id = None

        # Force flush on session end
        self.flush()

        if self.verbose:
            print(
                f"[AgentLens] Session ended: {sid[:8]}... "
                f"cost=${session.total_cost_usd:.4f} "
                f"tokens={session.total_tokens} "
                f"steps={session.total_steps}"
            )

    # ─── Event Recording ─────────────────────────────────────
    def record_llm_call(
        self,
        model: str,
        prompt: Any,
        completion: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        latency_ms: float = 0,
        provider: str = "openai",
        session_id: Optional[str] = None,
        parent_id: Optional[str] = None,
        tags: Optional[dict] = None,
    ):
        event = Event(
            event_type=EventType.LLM_RESPONSE,
            session_id=session_id or self._current_session_id or "",
            agent_name=self._get_agent_name(session_id),
            project_id=self.project,
            model=model,
            provider=provider,
            prompt=self._serialize(prompt),
            completion=completion[:2000] if completion else None,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            latency_ms=latency_ms,
            tags=tags or {},
            success=True,
        )
        event.compute_cost()

        # Update session stats
        sid = session_id or self._current_session_id
        if sid and sid in self._active_sessions:
            s = self._active_sessions[sid]
            s.total_llm_calls += 1
            s.total_tokens += (input_tokens + output_tokens)
            s.total_cost_usd += (event.cost_usd or 0)

        self._record(event)

    def record_tool_call(
        self,
        tool_name: str,
        args: Optional[dict] = None,
        result: Any = None,
        duration_ms: float = 0,
        success: bool = True,
        error: Optional[str] = None,
        session_id: Optional[str] = None,
        parent_id: Optional[str] = None,
        tags: Optional[dict] = None,
    ):
        event = Event(
            event_type=EventType.TOOL_RESULT if success else EventType.TOOL_ERROR,
            session_id=session_id or self._current_session_id or "",
            agent_name=self._get_agent_name(session_id),
            project_id=self.project,
            tool_name=tool_name,
            tool_args=args,
            tool_result=self._serialize(result)[:1000] if result else None,
            duration_ms=duration_ms,
            success=success,
            error_message=error,
            tags=tags or {},
        )

        sid = session_id or self._current_session_id
        if sid and sid in self._active_sessions:
            s = self._active_sessions[sid]
            s.total_tool_calls += 1
            if not success:
                s.error_count += 1

        self._record(event)

    def record_step(
        self,
        step_number: int,
        thought: Optional[str] = None,
        decision: Optional[str] = None,
        session_id: Optional[str] = None,
        tags: Optional[dict] = None,
    ):
        event = Event(
            event_type=EventType.AGENT_STEP,
            session_id=session_id or self._current_session_id or "",
            agent_name=self._get_agent_name(session_id),
            project_id=self.project,
            step_number=step_number,
            thought=thought,
            decision=decision,
            tags=tags or {},
        )

        sid = session_id or self._current_session_id
        if sid and sid in self._active_sessions:
            self._active_sessions[sid].total_steps += 1

        self._record(event)

    def record_error(
        self,
        error: Exception,
        context: str = "",
        session_id: Optional[str] = None,
    ):
        import traceback

        event = Event(
            event_type=EventType.ERROR,
            session_id=session_id or self._current_session_id or "",
            agent_name=self._get_agent_name(session_id),
            project_id=self.project,
            error_message=str(error),
            error_type=type(error).__name__,
            stack_trace=traceback.format_exc(),
            meta={"context": context} if context else {},
            success=False,
        )

        sid = session_id or self._current_session_id
        if sid and sid in self._active_sessions:
            self._active_sessions[sid].error_count += 1

        self._record(event)

    def record_custom(
        self,
        name: str,
        data: Any = None,
        session_id: Optional[str] = None,
        tags: Optional[dict] = None,
    ):
        self._record(Event(
            event_type=EventType.CUSTOM,
            session_id=session_id or self._current_session_id or "",
            agent_name=self._get_agent_name(session_id),
            project_id=self.project,
            tool_name=name,
            meta={"data": self._serialize(data)} if data else {},
            tags=tags or {},
        ))

    # ─── Monitor decorator ───────────────────────────────────
    def monitor(self, agent_name: str = "default", tags: Optional[dict] = None):
        """Decorator to auto-monitor an agent function.

        Usage:
            @lens.monitor("booking-agent")
            def my_agent(task):
                ...
        """
        from .decorators import _make_monitor
        return _make_monitor(self, agent_name, tags)

    # ─── Stats ───────────────────────────────────────────────
    def stats(self) -> dict:
        """Get client-side stats for diagnostics."""
        with self._lock:
            buffer_size = len(self._buffer)
        return {
            "events_sent": self._total_events_sent,
            "events_dropped": self._total_events_dropped,
            "flush_failures": self._total_flush_failures,
            "buffer_size": buffer_size,
            "circuit_state": self._circuit.state,
            "active_sessions": len(self._active_sessions),
        }

    # ─── Shutdown / Drain ────────────────────────────────────
    def shutdown(self):
        """Gracefully drain all buffered events before exit."""
        if self._shutting_down:
            return
        self._shutting_down = True

        if self.verbose:
            print("[AgentLens] Shutting down — draining buffer...")

        # End all active sessions as failed (abnormal shutdown)
        for sid in list(self._active_sessions.keys()):
            try:
                self.end_session(session_id=sid, success=False, output_data="Process shutdown")
            except Exception:
                pass

        # Attempt to flush remaining events with retries
        deadline = time.time() + self.drain_timeout
        while time.time() < deadline:
            with self._lock:
                if not self._buffer:
                    break
            self.flush()
            time.sleep(0.1)

        # If still have events, dump to DLQ
        with self._lock:
            if self._buffer:
                self._write_to_dlq(self._buffer)
                if self.verbose:
                    print(f"[AgentLens] Saved {len(self._buffer)} unsent events to DLQ: {self.dlq_path}")
                self._buffer.clear()

        if self.verbose:
            print(f"[AgentLens] Shutdown complete. Sent={self._total_events_sent} Dropped={self._total_events_dropped}")

    # ─── Internal ────────────────────────────────────────────
    def _record(self, event: Event):
        if not self.enabled:
            return

        # Inject user_id from context if not set
        if not event.user_id and self._current_user_id:
            event.user_id = self._current_user_id

        # Inject global metadata
        if self._global_metadata:
            if event.meta:
                merged = {**self._global_metadata, **event.meta}
                event.meta = merged
            else:
                event.meta = dict(self._global_metadata)

        # Sampling — skip events randomly based on sample_rate
        if self.sample_rate < 1.0:
            import random
            if random.random() > self.sample_rate:
                return

        with self._lock:
            # Buffer overflow protection
            if len(self._buffer) >= self.max_buffer_size:
                dropped = self._buffer[:self.batch_size]
                self._buffer = self._buffer[self.batch_size:]
                self._total_events_dropped += len(dropped)
                self._write_to_dlq(dropped)
                if self.verbose:
                    print(f"[AgentLens] Buffer overflow — dropped {len(dropped)} oldest events to DLQ")

            self._buffer.append(event.to_dict())
            if len(self._buffer) >= self.batch_size:
                self._do_flush()

    def _flush_loop(self):
        while not self._shutting_down:
            self._flush_event.wait(timeout=self.flush_interval)
            self._flush_event.clear()
            if not self._shutting_down:
                self.flush()

    def flush(self):
        with self._lock:
            self._do_flush()

    def _do_flush(self):
        """Flush buffer with retry + exponential backoff + circuit breaker."""
        if not self._buffer:
            return

        # Circuit breaker check
        if not self._circuit.can_execute():
            if self.verbose:
                print(f"[AgentLens] Circuit OPEN — skipping flush ({self._circuit.failure_count} consecutive failures)")
            return

        batch = self._buffer.copy()
        self._buffer.clear()

        success = False
        last_error = None

        for attempt in range(self.max_retries + 1):
            try:
                payload = json.dumps({"events": batch}).encode("utf-8")
                req = Request(
                    f"{self.server_url}/api/v1/events",
                    data=payload,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {self.api_key}",
                        "X-Project": self.project,
                    },
                    method="POST",
                )
                with urlopen(req, timeout=10) as resp:
                    if resp.status == 200:
                        self._circuit.record_success()
                        self._total_events_sent += len(batch)
                        success = True
                        break
                    elif resp.status == 429:
                        # Rate limited — back off more aggressively
                        delay = self.retry_base_delay * (2 ** attempt) * 2
                        if self.verbose:
                            print(f"[AgentLens] Rate limited (429). Retry in {delay:.1f}s")
                        time.sleep(delay)
                        continue
                    else:
                        last_error = f"HTTP {resp.status}"
                        if self.verbose:
                            print(f"[AgentLens] Flush failed: HTTP {resp.status} (attempt {attempt + 1}/{self.max_retries + 1})")

            except URLError as e:
                last_error = str(e)
                if self.verbose:
                    print(f"[AgentLens] Flush failed: {e} (attempt {attempt + 1}/{self.max_retries + 1})")
            except Exception as e:
                last_error = str(e)
                if self.verbose:
                    print(f"[AgentLens] Flush error: {e} (attempt {attempt + 1}/{self.max_retries + 1})")

            # Exponential backoff before retry
            if attempt < self.max_retries:
                delay = self.retry_base_delay * (2 ** attempt)
                time.sleep(min(delay, 30.0))  # Cap at 30s

        if not success:
            self._circuit.record_failure()
            self._total_flush_failures += 1

            # Write failed batch to Dead Letter Queue
            self._write_to_dlq(batch)

            if self.verbose:
                print(f"[AgentLens] All {self.max_retries + 1} attempts failed. {len(batch)} events written to DLQ.")

            # Fire failure callback
            if self.on_flush_failure:
                try:
                    self.on_flush_failure(batch, last_error)
                except Exception:
                    pass

    # ─── Dead Letter Queue ───────────────────────────────────
    def _write_to_dlq(self, events: list[dict]):
        """Append failed events to a JSONL file so they're never lost."""
        try:
            dlq_dir = os.path.dirname(self.dlq_path)
            if dlq_dir and not os.path.exists(dlq_dir):
                os.makedirs(dlq_dir, exist_ok=True)

            with open(self.dlq_path, "a", encoding="utf-8") as f:
                for event in events:
                    record = {
                        "failed_at": time.time(),
                        "project": self.project,
                        "event": event,
                    }
                    f.write(json.dumps(record, default=str) + "\n")
        except Exception as e:
            if self.verbose:
                print(f"[AgentLens] DLQ write failed: {e}")
            self._total_events_dropped += len(events)

    def _replay_dlq(self):
        """On startup, try to replay events from the Dead Letter Queue."""
        if not os.path.exists(self.dlq_path):
            return

        try:
            replayed = 0
            events_to_replay = []
            with open(self.dlq_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        record = json.loads(line)
                        events_to_replay.append(record["event"])
                        replayed += 1

            if events_to_replay:
                if self.verbose:
                    print(f"[AgentLens] Found {replayed} events in DLQ, replaying...")

                # Add to buffer for next flush
                with self._lock:
                    self._buffer.extend(events_to_replay)

                # Clear the DLQ file
                os.remove(self.dlq_path)
        except Exception as e:
            if self.verbose:
                print(f"[AgentLens] DLQ replay failed: {e}")

    def replay_dlq_manual(self) -> int:
        """Manually trigger DLQ replay. Returns count of events replayed."""
        if not os.path.exists(self.dlq_path):
            return 0
        self._replay_dlq()
        return len(self._buffer)

    # ─── Helpers ─────────────────────────────────────────────
    def _get_agent_name(self, session_id: Optional[str] = None) -> str:
        sid = session_id or self._current_session_id
        if sid and sid in self._active_sessions:
            return self._active_sessions[sid].agent_name
        return "unknown"

    @staticmethod
    def _serialize(obj: Any) -> str:
        if obj is None:
            return ""
        if isinstance(obj, str):
            return obj
        try:
            return json.dumps(obj, default=str, ensure_ascii=False)
        except Exception:
            return str(obj)
