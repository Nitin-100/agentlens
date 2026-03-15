"""
Prometheus-compatible /metrics endpoint for AgentLens.
Exposes counters, gauges, and histograms in Prometheus text exposition format.
No external dependencies — uses stdlib only.
"""

import time
import threading
from typing import Optional


class Gauge:
    def __init__(self, name: str, help_text: str):
        self.name = name
        self.help_text = help_text
        self._value = 0.0
        self._labels: dict[tuple, float] = {}
        self._lock = threading.Lock()

    def set(self, value: float, labels: Optional[dict] = None):
        with self._lock:
            if labels:
                self._labels[tuple(sorted(labels.items()))] = value
            else:
                self._value = value

    def render(self) -> str:
        lines = [f"# HELP {self.name} {self.help_text}", f"# TYPE {self.name} gauge"]
        with self._lock:
            if self._labels:
                for lk, v in self._labels.items():
                    lbl = ",".join(f'{k}="{v}"' for k, v in lk)
                    lines.append(f"{self.name}{{{lbl}}} {v}")
            else:
                lines.append(f"{self.name} {self._value}")
        return "\n".join(lines)


class Counter:
    def __init__(self, name: str, help_text: str):
        self.name = name
        self.help_text = help_text
        self._value = 0.0
        self._labels: dict[tuple, float] = {}
        self._lock = threading.Lock()

    def inc(self, amount: float = 1.0, labels: Optional[dict] = None):
        with self._lock:
            if labels:
                key = tuple(sorted(labels.items()))
                self._labels[key] = self._labels.get(key, 0) + amount
            else:
                self._value += amount

    def render(self) -> str:
        lines = [f"# HELP {self.name} {self.help_text}", f"# TYPE {self.name} counter"]
        with self._lock:
            if self._labels:
                for lk, v in self._labels.items():
                    lbl = ",".join(f'{k}="{v}"' for k, v in lk)
                    lines.append(f"{self.name}{{{lbl}}} {v}")
            else:
                lines.append(f"{self.name} {self._value}")
        return "\n".join(lines)


class Histogram:
    """Simple histogram with configurable buckets."""
    DEFAULT_BUCKETS = [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]

    def __init__(self, name: str, help_text: str, buckets=None):
        self.name = name
        self.help_text = help_text
        self.buckets = sorted(buckets or self.DEFAULT_BUCKETS)
        self._counts = {b: 0 for b in self.buckets}
        self._counts[float("inf")] = 0
        self._sum = 0.0
        self._count = 0
        self._lock = threading.Lock()

    def observe(self, value: float):
        with self._lock:
            self._sum += value
            self._count += 1
            for b in self.buckets:
                if value <= b:
                    self._counts[b] += 1
                    break
            self._counts[float("inf")] += 1

    def render(self) -> str:
        lines = [f"# HELP {self.name} {self.help_text}", f"# TYPE {self.name} histogram"]
        with self._lock:
            cumulative = 0
            for b in self.buckets:
                cumulative += self._counts[b]
                lines.append(f'{self.name}_bucket{{le="{b}"}} {cumulative}')
            lines.append(f'{self.name}_bucket{{le="+Inf"}} {self._counts[float("inf")]}')
            lines.append(f"{self.name}_sum {self._sum}")
            lines.append(f"{self.name}_count {self._count}")
        return "\n".join(lines)


# ─── Global Metrics Registry ─────────────────────────────────

# Counters
events_total = Counter("agentlens_events_total", "Total events ingested")
events_by_type = Counter("agentlens_events_by_type_total", "Events ingested by type")
sessions_total = Counter("agentlens_sessions_total", "Total sessions started")
errors_total = Counter("agentlens_errors_total", "Total errors recorded")
cost_total = Counter("agentlens_cost_usd_total", "Total cost in USD")
tokens_total = Counter("agentlens_tokens_total", "Total tokens consumed")
api_requests_total = Counter("agentlens_api_requests_total", "Total HTTP API requests")

# Gauges
active_sessions = Gauge("agentlens_active_sessions", "Currently active sessions")
active_websockets = Gauge("agentlens_active_websocket_connections", "Active WebSocket connections")
uptime_seconds = Gauge("agentlens_uptime_seconds", "Server uptime in seconds")
buffer_size = Gauge("agentlens_sdk_buffer_size", "SDK buffer size (last reported)")

# Histograms
latency_histogram = Histogram(
    "agentlens_llm_latency_seconds",
    "LLM call latency in seconds",
    buckets=[0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0],
)
cost_histogram = Histogram(
    "agentlens_llm_cost_usd",
    "LLM call cost in USD",
    buckets=[0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0],
)

_start_time = time.time()
_all_metrics = [
    events_total, events_by_type, sessions_total, errors_total, cost_total,
    tokens_total, api_requests_total,
    active_sessions, active_websockets, uptime_seconds, buffer_size,
    latency_histogram, cost_histogram,
]


def record_event(event: dict):
    """Call this on every event ingested to update metrics."""
    events_total.inc()
    event_type = event.get("event_type", "unknown")
    events_by_type.inc(labels={"type": event_type})

    if event_type in ("session.start", "session_start"):
        sessions_total.inc()
    if "error" in event_type:
        errors_total.inc()

    cost = event.get("cost_usd")
    if cost and cost > 0:
        cost_total.inc(cost)
        cost_histogram.observe(cost)

    tokens = event.get("total_tokens")
    if tokens and tokens > 0:
        tokens_total.inc(tokens)

    latency = event.get("latency_ms")
    if latency and latency > 0:
        latency_histogram.observe(latency / 1000.0)  # Convert ms to seconds


def render_metrics() -> str:
    """Render all metrics in Prometheus text exposition format."""
    uptime_seconds.set(time.time() - _start_time)
    return "\n\n".join(m.render() for m in _all_metrics) + "\n"
