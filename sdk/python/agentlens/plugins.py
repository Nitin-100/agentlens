"""
AgentLens Plugin System — Production-grade extensibility.

Provides a pluggable architecture for:
  - Database backends (SQLite, PostgreSQL, ClickHouse, DynamoDB, etc.)
  - Event exporters (S3, Kafka, Webhook, File, DataDog, etc.)
  - Event processors (filtering, enrichment, sampling, PII redaction)
  - Connection adapters (custom auth, custom transports)

Architecture:
    ┌──────────────┐     ┌────────────────┐     ┌──────────────────┐
    │   SDK Event   │────►│ Event Pipeline │────►│  Event Exporters │
    │   (ingress)   │     │  (processors)  │     │ (DB + external)  │
    └──────────────┘     └────────────────┘     └──────────────────┘
                                │
                          ┌─────┴──────┐
                          │  Plugins   │
                          │ registered │
                          │  via API   │
                          └────────────┘

Usage:
    from agentlens.plugins import PluginRegistry, DatabasePlugin, ExporterPlugin

    # Register a custom database
    registry = PluginRegistry.get_instance()
    registry.register_database(PostgreSQLPlugin(dsn="..."))

    # Register a custom exporter
    registry.register_exporter(S3Exporter(bucket="my-bucket"))

    # Register an event processor
    registry.register_processor(PIIRedactor())
"""

import logging
import threading
from typing import Callable, List, Optional
from abc import ABC, abstractmethod
from dataclasses import dataclass

logger = logging.getLogger("agentlens.plugins")


# ──────────────────────────────────────────────────────────────
# Plugin Interfaces (ABCs)
# ──────────────────────────────────────────────────────────────

class DatabasePlugin(ABC):
    """Interface for database backend plugins.

    Implement this to store AgentLens data in PostgreSQL, ClickHouse,
    MongoDB, DynamoDB, or any custom database.
    """

    @abstractmethod
    async def init(self) -> None:
        """Initialize connection pool, create tables if needed."""
        ...

    @abstractmethod
    async def insert_events(self, events: List[dict]) -> int:
        """Insert a batch of events. Returns count inserted."""
        ...

    @abstractmethod
    async def insert_session(self, session: dict) -> None:
        """Insert or update a session record."""
        ...

    @abstractmethod
    async def get_sessions(self, limit: int = 50, offset: int = 0,
                           agent: Optional[str] = None, project: Optional[str] = None) -> dict:
        """Get paginated sessions. Returns {sessions: [...], total: N}."""
        ...

    @abstractmethod
    async def get_session_detail(self, session_id: str) -> dict:
        """Get session with all its events. Returns {session: {...}, events: [...]}."""
        ...

    @abstractmethod
    async def get_events(self, limit: int = 100, event_type: Optional[str] = None,
                         session_id: Optional[str] = None) -> List[dict]:
        """Get events with optional filtering."""
        ...

    @abstractmethod
    async def get_analytics(self, hours: int = 24, project: Optional[str] = None) -> dict:
        """Get aggregated analytics for the given time window."""
        ...

    @abstractmethod
    async def cleanup(self, days: int = 30) -> dict:
        """Delete data older than N days. Returns {deleted_events, deleted_sessions}."""
        ...

    @abstractmethod
    async def health_check(self) -> dict:
        """Return health status. {status: 'ok', ...details}."""
        ...

    async def close(self) -> None:
        """Clean up resources."""
        pass

    @property
    def name(self) -> str:
        return self.__class__.__name__


class ExporterPlugin(ABC):
    """Interface for event export plugins.

    Events flow through exporters AFTER being stored in the database.
    Use for: S3 archival, Kafka streaming, webhook forwarding,
    DataDog/Prometheus metrics, file logging, etc.
    """

    @abstractmethod
    async def export_events(self, events: List[dict]) -> None:
        """Export a batch of events to external system."""
        ...

    async def export_session(self, session: dict) -> None:
        """Export a session summary. Optional — default does nothing."""
        pass

    async def export_alert(self, alert: dict) -> None:
        """Export a triggered alert. Optional."""
        pass

    async def init(self) -> None:
        """Initialize the exporter (connections, auth, etc.)."""
        pass

    async def close(self) -> None:
        """Clean up resources."""
        pass

    @property
    def name(self) -> str:
        return self.__class__.__name__


class EventProcessor(ABC):
    """Interface for event processing plugins.

    Processors run BEFORE events are stored. Use for:
    filtering, enrichment, PII redaction, sampling, transformation.
    """

    @abstractmethod
    def process(self, event: dict) -> Optional[dict]:
        """Process an event. Return modified event or None to drop it."""
        ...

    @property
    def name(self) -> str:
        return self.__class__.__name__

    @property
    def priority(self) -> int:
        """Lower number = runs first. Default 100."""
        return 100


# ──────────────────────────────────────────────────────────────
# Event Hooks
# ──────────────────────────────────────────────────────────────

@dataclass
class EventHook:
    """A callback that fires on specific event types."""
    name: str
    event_types: List[str]  # e.g., ["error", "session.end", "*"]
    callback: Callable[[dict], None]
    async_callback: Optional[Callable] = None
    enabled: bool = True


# ──────────────────────────────────────────────────────────────
# Plugin Registry (Singleton)
# ──────────────────────────────────────────────────────────────

class PluginRegistry:
    """Central registry for all AgentLens plugins.

    Singleton — access via PluginRegistry.get_instance().

    Usage:
        registry = PluginRegistry.get_instance()

        # Database backends (only one active at a time)
        registry.register_database(PostgreSQLPlugin(...))

        # Exporters (multiple can be active)
        registry.register_exporter(S3Exporter(...))
        registry.register_exporter(KafkaExporter(...))

        # Processors (run in priority order)
        registry.register_processor(PIIRedactor())

        # Hooks (fire on specific events)
        registry.on("error", lambda event: send_slack_alert(event))
    """

    _instance = None
    _lock = threading.Lock()

    def __init__(self):
        self._database: Optional[DatabasePlugin] = None
        self._exporters: List[ExporterPlugin] = []
        self._processors: List[EventProcessor] = []
        self._hooks: List[EventHook] = []
        self._initialized = False

    @classmethod
    def get_instance(cls) -> "PluginRegistry":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls):
        """Reset for testing."""
        cls._instance = None

    # ─── Registration ────────────────────────────────────────

    def register_database(self, plugin: DatabasePlugin) -> None:
        """Register a database backend. Replaces any existing one."""
        old = self._database
        self._database = plugin
        logger.info(f"Database plugin registered: {plugin.name}" +
                    (f" (replaced {old.name})" if old else ""))

    def register_exporter(self, plugin: ExporterPlugin) -> None:
        """Register an event exporter. Multiple can be active."""
        self._exporters.append(plugin)
        logger.info(f"Exporter plugin registered: {plugin.name} (total: {len(self._exporters)})")

    def register_processor(self, plugin: EventProcessor) -> None:
        """Register an event processor. Runs in priority order."""
        self._processors.append(plugin)
        self._processors.sort(key=lambda p: p.priority)
        logger.info(f"Processor plugin registered: {plugin.name} (priority: {plugin.priority})")

    def on(self, event_type: str, callback: Callable, name: str = "") -> None:
        """Register a hook that fires on a specific event type.

        Use "*" to fire on all events.
        Use "error" to fire on error events.
        Use "session.end" to fire on session end events.
        """
        hook = EventHook(
            name=name or f"hook_{len(self._hooks)}",
            event_types=[event_type],
            callback=callback,
        )
        self._hooks.append(hook)
        logger.info(f"Hook registered: {hook.name} for event type '{event_type}'")

    def on_async(self, event_type: str, callback: Callable, name: str = "") -> None:
        """Register an async hook."""
        hook = EventHook(
            name=name or f"async_hook_{len(self._hooks)}",
            event_types=[event_type],
            async_callback=callback,
        )
        self._hooks.append(hook)

    # ─── Accessors ───────────────────────────────────────────

    @property
    def database(self) -> Optional[DatabasePlugin]:
        return self._database

    @property
    def exporters(self) -> List[ExporterPlugin]:
        return self._exporters

    @property
    def processors(self) -> List[EventProcessor]:
        return self._processors

    @property
    def hooks(self) -> List[EventHook]:
        return self._hooks

    # ─── Pipeline ────────────────────────────────────────────

    def process_events(self, events: List[dict]) -> List[dict]:
        """Run all processors on a batch of events. Returns filtered/modified events."""
        if not self._processors:
            return events

        result = []
        for event in events:
            processed = event
            for processor in self._processors:
                try:
                    processed = processor.process(processed)
                    if processed is None:
                        break  # Event dropped by processor
                except Exception as e:
                    logger.error(f"Processor {processor.name} error: {e}")
                    # Don't drop the event on processor error
                    processed = event
            if processed is not None:
                result.append(processed)

        return result

    def fire_hooks(self, event: dict) -> None:
        """Fire all matching hooks for an event. Non-blocking."""
        event_type = event.get("event_type", "")

        for hook in self._hooks:
            if not hook.enabled:
                continue
            if "*" in hook.event_types or event_type in hook.event_types:
                try:
                    if hook.callback:
                        hook.callback(event)
                except Exception as e:
                    logger.error(f"Hook {hook.name} error: {e}")

    async def fire_hooks_async(self, event: dict) -> None:
        """Fire async hooks."""
        event_type = event.get("event_type", "")

        for hook in self._hooks:
            if not hook.enabled:
                continue
            if "*" in hook.event_types or event_type in hook.event_types:
                try:
                    if hook.async_callback:
                        await hook.async_callback(event)
                    elif hook.callback:
                        hook.callback(event)
                except Exception as e:
                    logger.error(f"Async hook {hook.name} error: {e}")

    async def export_events(self, events: List[dict]) -> None:
        """Send events to all registered exporters."""
        for exporter in self._exporters:
            try:
                await exporter.export_events(events)
            except Exception as e:
                logger.error(f"Exporter {exporter.name} error: {e}")

    async def export_session(self, session: dict) -> None:
        """Send session to all registered exporters."""
        for exporter in self._exporters:
            try:
                await exporter.export_session(session)
            except Exception as e:
                logger.error(f"Exporter {exporter.name} session export error: {e}")

    async def init_all(self) -> None:
        """Initialize all plugins."""
        if self._initialized:
            return

        if self._database:
            await self._database.init()
            logger.info(f"Database plugin initialized: {self._database.name}")

        for exporter in self._exporters:
            await exporter.init()
            logger.info(f"Exporter initialized: {exporter.name}")

        self._initialized = True

    async def close_all(self) -> None:
        """Clean up all plugins."""
        if self._database:
            await self._database.close()

        for exporter in self._exporters:
            await exporter.close()

        self._initialized = False

    # ─── Info ────────────────────────────────────────────────

    def info(self) -> dict:
        """Get info about registered plugins."""
        return {
            "database": self._database.name if self._database else "default (SQLite)",
            "exporters": [e.name for e in self._exporters],
            "processors": [f"{p.name} (priority={p.priority})" for p in self._processors],
            "hooks": [f"{h.name} → {h.event_types}" for h in self._hooks],
        }
