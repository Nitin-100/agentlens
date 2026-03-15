"""
SDK Unit Tests — tests for the core AgentLens SDK.
No server required. Tests event creation, batching, circuit breaker,
PII redaction, plugin system, decorators, and session management.
"""

import os
import sys
import time
import json
import uuid
import tempfile
import threading

import pytest

# Add SDK to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "sdk", "python"))

from agentlens.events import Event, EventType, Session, estimate_cost, MODEL_COSTS
from agentlens.plugins import PluginRegistry, DatabasePlugin, ExporterPlugin, EventProcessor
from agentlens.builtin_plugins import (
    PIIRedactor, SamplingProcessor, FilterProcessor, EnrichmentProcessor,
    FileExporter,
)


# ─── Event & Session Tests ───────────────────────────────────

class TestEvent:
    def test_create_event(self):
        e = Event(event_type=EventType.LLM_RESPONSE, agent_name="test-agent")
        assert e.event_type == "llm.response"
        assert e.agent_name == "test-agent"
        assert e.event_id is not None
        assert e.timestamp > 0

    def test_event_to_dict(self):
        e = Event(event_type=EventType.SESSION_START, agent_name="a", session_id="s1")
        d = e.to_dict()
        assert d["event_type"] == "session.start"
        assert d["agent_name"] == "a"
        assert d["session_id"] == "s1"
        assert "event_id" in d
        # None values should be stripped
        assert "model" not in d

    def test_event_types_are_dot_notation(self):
        assert EventType.SESSION_START == "session.start"
        assert EventType.LLM_RESPONSE == "llm.response"
        assert EventType.TOOL_CALL == "tool.call"
        assert EventType.ERROR == "error"


class TestSession:
    def test_create_session(self):
        s = Session(agent_name="my-agent", project_id="test")
        assert s.agent_name == "my-agent"
        assert s.session_id is not None
        assert s.started_at > 0
        assert s.success is None

    def test_session_to_dict(self):
        s = Session(agent_name="x", project_id="p")
        d = s.to_dict()
        assert d["agent_name"] == "x"
        assert d["project_id"] == "p"
        assert "session_id" in d


class TestCostEstimation:
    def test_known_models(self):
        cost = estimate_cost("gpt-4o", 1000, 500)
        assert cost > 0
        assert isinstance(cost, float)

    def test_unknown_model_zero_cost(self):
        cost = estimate_cost("my-custom-model", 1000, 500)
        assert cost == 0

    def test_gpt4o_mini_cheaper_than_gpt4o(self):
        cost_mini = estimate_cost("gpt-4o-mini", 1000, 500)
        cost_full = estimate_cost("gpt-4o", 1000, 500)
        assert cost_mini <= cost_full

    def test_model_costs_has_entries(self):
        assert len(MODEL_COSTS) > 10


# ─── PII Redactor Tests ─────────────────────────────────────

class TestPIIRedactor:
    def setup_method(self):
        self.redactor = PIIRedactor()

    def test_redact_email(self):
        event = {"data": "Contact user@example.com for info"}
        result = self.redactor.process(event)
        assert "[EMAIL_REDACTED]" in result["data"]
        assert "user@example.com" not in result["data"]

    def test_redact_phone(self):
        event = {"data": "Call 555-123-4567 now"}
        result = self.redactor.process(event)
        assert "[PHONE_REDACTED]" in result["data"]

    def test_redact_ssn(self):
        event = {"data": "SSN: 123-45-6789"}
        result = self.redactor.process(event)
        assert "[SSN_REDACTED]" in result["data"]

    def test_redact_api_key(self):
        event = {"data": "token secret_abcdefghijklmnopqrstuvwxyz123"}
        result = self.redactor.process(event)
        assert "[API_KEY_REDACTED]" in result["data"]

    def test_redact_credit_card(self):
        event = {"data": "Card: 4111 1111 1111 1111 end"}
        result = self.redactor.process(event)
        # Credit card should be redacted (either CC or phone pattern catches it)
        assert "4111 1111 1111 1111" not in result["data"]

    def test_redact_nested_dict(self):
        event = {"data": {"inner": "email: user@test.com", "nested": {"deep": "555-111-2222"}}}
        result = self.redactor.process(event)
        assert "[EMAIL_REDACTED]" in result["data"]["inner"]
        assert "[PHONE_REDACTED]" in result["data"]["nested"]["deep"]

    def test_redact_list(self):
        event = {"items": ["user@a.com", "no-pii-here"]}
        result = self.redactor.process(event)
        assert "[EMAIL_REDACTED]" in result["items"][0]
        assert result["items"][1] == "no-pii-here"

    def test_no_false_positive_on_clean_data(self):
        event = {"data": "Hello world, this is a normal string"}
        result = self.redactor.process(event)
        assert result["data"] == "Hello world, this is a normal string"

    def test_custom_patterns(self):
        redactor = PIIRedactor(extra_patterns={
            "badge": (r"BADGE-\d{6}", "[BADGE_REDACTED]"),
        })
        event = {"data": "Employee BADGE-123456 entered"}
        result = redactor.process(event)
        assert "[BADGE_REDACTED]" in result["data"]


# ─── Sampling Processor Tests ────────────────────────────────

class TestSamplingProcessor:
    def test_always_keep_errors(self):
        proc = SamplingProcessor(rate=0.0)  # Drop everything
        event = {"event_type": "error", "agent_name": "test"}
        result = proc.process(event)
        assert result is not None  # Errors always kept

    def test_always_keep_session_start(self):
        proc = SamplingProcessor(rate=0.0)
        event = {"event_type": "session.start"}
        result = proc.process(event)
        assert result is not None

    def test_rate_zero_drops_normal(self):
        proc = SamplingProcessor(rate=0.0)
        event = {"event_type": "llm.response"}
        result = proc.process(event)
        assert result is None

    def test_rate_one_keeps_all(self):
        proc = SamplingProcessor(rate=1.0)
        kept = sum(1 for _ in range(100) if proc.process({"event_type": "llm.response"}) is not None)
        assert kept == 100


# ─── Filter Processor Tests ─────────────────────────────────

class TestFilterProcessor:
    def test_drop_types(self):
        proc = FilterProcessor(drop_types=["custom.debug"])
        assert proc.process({"event_type": "custom.debug"}) is None
        assert proc.process({"event_type": "llm.response"}) is not None

    def test_keep_types(self):
        proc = FilterProcessor(keep_types=["error", "llm.response"])
        assert proc.process({"event_type": "error"}) is not None
        assert proc.process({"event_type": "tool.call"}) is None

    def test_drop_agents(self):
        proc = FilterProcessor(drop_agents=["noisy-agent"])
        assert proc.process({"event_type": "x", "agent_name": "noisy-agent"}) is None
        assert proc.process({"event_type": "x", "agent_name": "good-agent"}) is not None

    def test_custom_predicate(self):
        proc = FilterProcessor(predicate=lambda e: e.get("importance", 0) > 5)
        assert proc.process({"event_type": "x", "importance": 10}) is not None
        assert proc.process({"event_type": "x", "importance": 1}) is None


# ─── Enrichment Processor Tests ──────────────────────────────

class TestEnrichmentProcessor:
    def test_static_metadata(self):
        proc = EnrichmentProcessor(metadata={"env": "test", "version": "1.0"})
        result = proc.process({"event_type": "x"})
        assert result["env"] == "test"
        assert result["version"] == "1.0"
        assert result["event_type"] == "x"

    def test_dynamic_enricher(self):
        proc = EnrichmentProcessor(enricher=lambda e: {"processed_at": 12345})
        result = proc.process({"event_type": "x"})
        assert result["processed_at"] == 12345


# ─── Plugin Registry Tests ───────────────────────────────────

class TestPluginRegistry:
    def setup_method(self):
        # Reset singleton for test isolation
        PluginRegistry._instance = None

    def test_singleton(self):
        r1 = PluginRegistry.get_instance()
        r2 = PluginRegistry.get_instance()
        assert r1 is r2

    def test_register_processor(self):
        reg = PluginRegistry.get_instance()
        reg.register_processor(PIIRedactor())
        info = reg.info()
        assert len(info["processors"]) == 1
        assert "PIIRedactor" in info["processors"][0]

    def test_processor_priority_ordering(self):
        reg = PluginRegistry.get_instance()
        reg.register_processor(EnrichmentProcessor(metadata={"x": 1}))  # priority=50
        reg.register_processor(SamplingProcessor(rate=1.0))  # priority=5
        reg.register_processor(PIIRedactor())  # priority=10
        info = reg.info()
        # Should be sorted by priority: Sampling(5), PII(10), Enrichment(50)
        assert "SamplingProcessor" in info["processors"][0]
        assert "PIIRedactor" in info["processors"][1]
        assert "EnrichmentProcessor" in info["processors"][2]

    def test_process_events_pipeline(self):
        reg = PluginRegistry.get_instance()
        reg.register_processor(PIIRedactor())
        reg.register_processor(EnrichmentProcessor(metadata={"env": "test"}))

        events = [{"event_type": "llm.response", "data": "user@test.com said hello"}]
        processed = reg.process_events(events)

        assert len(processed) == 1
        assert "[EMAIL_REDACTED]" in processed[0]["data"]
        assert processed[0]["env"] == "test"

    def test_process_events_drop(self):
        reg = PluginRegistry.get_instance()
        reg.register_processor(FilterProcessor(drop_types=["custom.debug"]))

        events = [
            {"event_type": "llm.response"},
            {"event_type": "custom.debug"},
            {"event_type": "error"},
        ]
        processed = reg.process_events(events)
        assert len(processed) == 2
        types = [e["event_type"] for e in processed]
        assert "custom.debug" not in types

    def test_hooks(self):
        reg = PluginRegistry.get_instance()
        captured = []

        def on_error(event):
            captured.append(event)

        reg.on("error", on_error)

        reg.fire_hooks({"event_type": "error", "msg": "test"})
        assert len(captured) == 1
        assert captured[0]["msg"] == "test"

    def test_info(self):
        reg = PluginRegistry.get_instance()
        info = reg.info()
        assert "database" in info
        assert "exporters" in info
        assert "processors" in info
        assert "hooks" in info


# ─── File Exporter Test ──────────────────────────────────────

class TestFileExporter:
    def test_export_writes_jsonl(self):
        import asyncio

        with tempfile.TemporaryDirectory() as tmpdir:
            exporter = FileExporter(directory=tmpdir)
            asyncio.run(exporter.init())
            asyncio.run(exporter.export_events([
                {"event_type": "llm.response", "model": "gpt-4o"},
                {"event_type": "error", "msg": "fail"},
            ]))

            # Check files exist
            files = os.listdir(tmpdir)
            assert len(files) == 1
            assert files[0].endswith(".jsonl")

            # Check content
            with open(os.path.join(tmpdir, files[0])) as f:
                lines = f.readlines()
            assert len(lines) == 2
            assert json.loads(lines[0])["model"] == "gpt-4o"


# ─── Circuit Breaker Tests ───────────────────────────────────

class TestCircuitBreaker:
    def test_starts_closed(self):
        from agentlens.client import CircuitBreaker
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=1.0)
        assert cb.can_execute() is True
        assert cb.state == "closed"

    def test_opens_after_threshold(self):
        from agentlens.client import CircuitBreaker
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60.0)
        cb.record_failure()
        cb.record_failure()
        assert cb.can_execute() is True  # Still closed
        cb.record_failure()
        assert cb.can_execute() is False  # Now OPEN
        assert cb.state == "open"

    def test_success_resets(self):
        from agentlens.client import CircuitBreaker
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        assert cb.failure_count == 0
        assert cb.state == "closed"

    def test_half_open_after_timeout(self):
        from agentlens.client import CircuitBreaker
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.1)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == "open"
        time.sleep(0.15)
        assert cb.can_execute() is True  # Now half-open
        assert cb.state == "half_open"


# ─── User Tracking Tests ────────────────────────────────────

class TestUserTracking:
    def test_event_user_id(self):
        """Event should support user_id field."""
        e = Event(event_type=EventType.LLM_RESPONSE, agent_name="a", user_id="u123")
        assert e.user_id == "u123"
        d = e.to_dict()
        assert d["user_id"] == "u123"

    def test_event_user_id_none_stripped(self):
        """None user_id should be stripped from to_dict."""
        e = Event(event_type=EventType.LLM_RESPONSE, agent_name="a")
        d = e.to_dict()
        assert "user_id" not in d

    def test_session_user_id(self):
        """Session should support user_id field."""
        s = Session(agent_name="a", user_id="user_abc")
        assert s.user_id == "user_abc"
        d = s.to_dict()
        assert d["user_id"] == "user_abc"

    def test_session_user_id_none(self):
        """Session without user_id should work."""
        s = Session(agent_name="a")
        assert s.user_id is None
        d = s.to_dict()
        assert "user_id" not in d
