"""
AgentLens OpenTelemetry Ingestion — Accept OTEL traces and map to AgentLens events.

Supports:
  - OTLP JSON format (POST /v1/traces)
  - Maps OTEL spans to AgentLens event model
  - Preserves parent_id for nested trace visualization
  - Extracts LLM-specific attributes (gen_ai.* namespace)
  - Works with Pydantic AI, Strands Agents, smolagents, AWS Bedrock AgentCore

Endpoint: POST /api/v1/otel/traces
Content-Type: application/json
"""

import time
import json
import uuid
import logging
from typing import Optional

logger = logging.getLogger("agentlens.otel")


# OTEL span kind mapping
SPAN_KIND_MAP = {
    0: "unspecified", 1: "internal", 2: "server",
    3: "client", 4: "producer", 5: "consumer",
}

# OTEL status codes
STATUS_OK = 1
STATUS_ERROR = 2

# gen_ai.* semantic conventions
GEN_AI_ATTRIBUTES = {
    "gen_ai.system", "gen_ai.request.model", "gen_ai.response.model",
    "gen_ai.request.max_tokens", "gen_ai.request.temperature",
    "gen_ai.usage.prompt_tokens", "gen_ai.usage.completion_tokens",
    "gen_ai.usage.total_tokens", "gen_ai.response.finish_reasons",
    "gen_ai.prompt", "gen_ai.completion",
}


def extract_attributes(attrs_list: list) -> dict:
    """Convert OTEL attribute list [{key, value}] to flat dict."""
    result = {}
    if not attrs_list:
        return result
    for attr in attrs_list:
        key = attr.get("key", "")
        value = attr.get("value", {})
        # OTEL values are typed: stringValue, intValue, doubleValue, boolValue, etc.
        if "stringValue" in value:
            result[key] = value["stringValue"]
        elif "intValue" in value:
            result[key] = int(value["intValue"])
        elif "doubleValue" in value:
            result[key] = float(value["doubleValue"])
        elif "boolValue" in value:
            result[key] = value["boolValue"]
        elif "arrayValue" in value:
            result[key] = [v.get("stringValue", str(v)) for v in value["arrayValue"].get("values", [])]
        else:
            result[key] = str(value)
    return result


def nano_to_epoch(nano_str) -> float:
    """Convert OTEL nanosecond timestamp to epoch seconds."""
    try:
        return int(nano_str) / 1_000_000_000
    except (ValueError, TypeError):
        return time.time()


def classify_span(span_name: str, attrs: dict, kind: int) -> str:
    """Map OTEL span to AgentLens event_type based on attributes and name."""
    name_lower = span_name.lower()

    # LLM calls (gen_ai semantic convention)
    if any(k.startswith("gen_ai.") for k in attrs):
        if attrs.get("gen_ai.system") or attrs.get("gen_ai.request.model"):
            return "llm.response"

    # Tool calls
    if "tool" in name_lower or attrs.get("tool.name"):
        if any(k in name_lower for k in ["error", "fail"]):
            return "tool.error"
        return "tool.result"

    # Agent steps
    if any(k in name_lower for k in ["agent", "step", "plan", "think", "reason", "decide"]):
        return "agent.step"

    # Errors
    if any(k in name_lower for k in ["error", "exception", "fail"]):
        return "error"

    # Session markers
    if "session" in name_lower and "start" in name_lower:
        return "session.start"
    if "session" in name_lower and ("end" in name_lower or "stop" in name_lower):
        return "session.end"

    # Client spans are often LLM calls
    if kind == 3:  # CLIENT
        return "llm.response"

    # Default: agent step
    return "agent.step"


def otel_span_to_event(span: dict, resource_attrs: dict, scope_name: str = "") -> dict:
    """Convert a single OTEL span to an AgentLens event dict."""
    attrs = extract_attributes(span.get("attributes", []))
    span_name = span.get("name", "unknown")
    span_kind = span.get("kind", 0)
    if isinstance(span_kind, str):
        span_kind = {"SPAN_KIND_INTERNAL": 1, "SPAN_KIND_SERVER": 2,
                      "SPAN_KIND_CLIENT": 3, "SPAN_KIND_PRODUCER": 4,
                      "SPAN_KIND_CONSUMER": 5}.get(span_kind, 0)

    status = span.get("status", {})
    status_code = status.get("code", 0)
    if isinstance(status_code, str):
        status_code = {"STATUS_CODE_OK": 1, "STATUS_CODE_ERROR": 2}.get(status_code, 0)

    event_type = classify_span(span_name, attrs, span_kind)

    # Timing
    start_time = nano_to_epoch(span.get("startTimeUnixNano", 0))
    end_time = nano_to_epoch(span.get("endTimeUnixNano", 0))
    duration_ms = (end_time - start_time) * 1000 if end_time > start_time else 0

    # Build event
    event = {
        "event_id": span.get("spanId", str(uuid.uuid4())[:16]),
        "event_type": event_type,
        "timestamp": start_time,
        "session_id": span.get("traceId", ""),
        "parent_id": span.get("parentSpanId", ""),
        "agent_name": resource_attrs.get("service.name", scope_name or "otel-agent"),
        "duration_ms": round(duration_ms, 2),
        "success": status_code != STATUS_ERROR,
        "meta": {
            "otel_span_name": span_name,
            "otel_span_kind": SPAN_KIND_MAP.get(span_kind, str(span_kind)),
            "otel_trace_id": span.get("traceId", ""),
            "otel_span_id": span.get("spanId", ""),
            "otel_parent_span_id": span.get("parentSpanId", ""),
            "otel_scope": scope_name,
        },
        "tags": {},
    }

    # Extract LLM-specific attributes
    model = attrs.get("gen_ai.request.model") or attrs.get("gen_ai.response.model")
    if model:
        event["model"] = model
        event["provider"] = attrs.get("gen_ai.system", "unknown")

    prompt_tokens = attrs.get("gen_ai.usage.prompt_tokens")
    completion_tokens = attrs.get("gen_ai.usage.completion_tokens")
    total_tokens = attrs.get("gen_ai.usage.total_tokens")
    if prompt_tokens is not None:
        event["input_tokens"] = int(prompt_tokens)
    if completion_tokens is not None:
        event["output_tokens"] = int(completion_tokens)
    if total_tokens is not None:
        event["total_tokens"] = int(total_tokens)
    elif prompt_tokens and completion_tokens:
        event["total_tokens"] = int(prompt_tokens) + int(completion_tokens)

    if event_type == "llm.response":
        event["latency_ms"] = round(duration_ms, 2)
        event["prompt"] = attrs.get("gen_ai.prompt", attrs.get("gen_ai.request.prompt", ""))
        event["completion"] = attrs.get("gen_ai.completion", attrs.get("gen_ai.response.completion", ""))

    # Tool attributes
    if event_type in ("tool.result", "tool.error"):
        event["tool_name"] = attrs.get("tool.name", span_name)
        tool_args_str = attrs.get("tool.parameters") or attrs.get("tool.args")
        if tool_args_str:
            try:
                event["tool_args"] = json.loads(tool_args_str) if isinstance(tool_args_str, str) else tool_args_str
            except (json.JSONDecodeError, TypeError):
                event["tool_args"] = {"raw": str(tool_args_str)}
        event["tool_result"] = attrs.get("tool.result", attrs.get("tool.output", ""))

    # Error attributes
    if status_code == STATUS_ERROR or event_type == "error":
        event["error_message"] = status.get("message", attrs.get("exception.message", ""))
        event["error_type"] = attrs.get("exception.type", "OTELError")
        event["stack_trace"] = attrs.get("exception.stacktrace", "")
        event["success"] = False

    # Step attributes
    if event_type == "agent.step":
        event["thought"] = attrs.get("agent.thought", attrs.get("agent.reasoning", span_name))
        event["decision"] = attrs.get("agent.decision", attrs.get("agent.action", ""))
        step_num = attrs.get("agent.step_number") or attrs.get("step.number")
        if step_num is not None:
            event["step_number"] = int(step_num)

    # Copy remaining attributes to tags
    for k, v in attrs.items():
        if not k.startswith("gen_ai.") and k not in ("tool.name", "tool.parameters", "tool.result"):
            event["tags"][k] = v

    return event


def parse_otel_traces(payload: dict) -> list[dict]:
    """Parse full OTLP JSON payload into a list of AgentLens events.

    Expected format:
    {
      "resourceSpans": [
        {
          "resource": {"attributes": [...]},
          "scopeSpans": [
            {
              "scope": {"name": "..."},
              "spans": [...]
            }
          ]
        }
      ]
    }
    """
    events = []

    for resource_span in payload.get("resourceSpans", []):
        resource = resource_span.get("resource", {})
        resource_attrs = extract_attributes(resource.get("attributes", []))

        for scope_span in resource_span.get("scopeSpans", []):
            scope = scope_span.get("scope", {})
            scope_name = scope.get("name", "")

            for span in scope_span.get("spans", []):
                try:
                    event = otel_span_to_event(span, resource_attrs, scope_name)
                    events.append(event)
                except Exception as e:
                    logger.warning(f"Failed to convert OTEL span: {e}")
                    continue

    logger.info(f"Parsed {len(events)} events from OTEL traces")
    return events
