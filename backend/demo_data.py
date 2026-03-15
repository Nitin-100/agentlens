"""
AgentLens Demo Data Generator — Populates realistic agent data.

Generates 500+ events across 5 different agent types:
  1. CustomerSupportBot — normal operation
  2. ResearchAgent — heavy tool usage
  3. CodeReviewAgent — occasional errors
  4. DataPipelineAgent — cost spike anomaly
  5. ChatBot — simple, high-volume

Includes one agent with a cost spike and one with error patterns.
"""

import time
import uuid
import random
import logging

logger = logging.getLogger("agentlens.demo")

MODELS = ["gpt-4o", "gpt-4o-mini", "claude-3.5-sonnet", "gemini-2.0-flash", "o3-mini"]
TOOLS = [
    ("web_search", {"query": "latest news"}, "Found 10 results"),
    ("database_query", {"sql": "SELECT * FROM users LIMIT 10"}, "10 rows returned"),
    ("send_email", {"to": "user@example.com", "subject": "Report"}, "Email sent"),
    ("file_read", {"path": "/data/config.json"}, '{"key": "value"}'),
    ("http_request", {"url": "https://api.example.com/data"}, '{"status": "ok"}'),
    ("calculator", {"expression": "42 * 3.14"}, "131.88"),
    ("code_execute", {"language": "python", "code": "print('hello')"}, "hello"),
    ("vector_search", {"query": "similar documents", "k": 5}, "5 documents found"),
]

PROMPTS = [
    "Analyze the quarterly revenue data and provide insights",
    "Help me debug this Python function that's throwing TypeError",
    "Summarize the key points from the attached research paper",
    "Generate a marketing email for our new product launch",
    "Review this code for security vulnerabilities",
    "Plan a 3-day trip to Tokyo with budget $2000",
    "Compare the performance of PostgreSQL vs MongoDB for our use case",
    "Write unit tests for the authentication module",
    "Explain the concept of transformer architecture in simple terms",
    "Create a data pipeline design for real-time analytics",
]

COMPLETIONS = [
    "Based on my analysis of the data, here are the key findings...",
    "I found the issue in your code. The TypeError occurs because...",
    "The paper presents three main contributions: 1) ...",
    "Here's a draft marketing email that highlights the key features...",
    "I've identified several potential security issues in the code...",
    "Here's your optimized 3-day Tokyo itinerary within budget...",
    "After comparing both databases, I recommend PostgreSQL for...",
    "I've generated 12 unit tests covering edge cases for authentication...",
    "Think of transformers like a team of readers who each focus on...",
    "The recommended pipeline architecture uses Apache Kafka for...",
]

ERROR_MESSAGES = [
    "Rate limit exceeded: 429 Too Many Requests",
    "Context window exceeded: maximum 128000 tokens",
    "API key expired or invalid",
    "Tool execution timeout after 30000ms",
    "JSON parsing error in tool response",
    "Network connection reset by peer",
    "Guardrail triggered: response contained PII",
]


def _gen_event_id():
    return f"evt_{uuid.uuid4().hex[:12]}"


def _gen_session_id():
    return f"sess_{uuid.uuid4().hex[:12]}"


def generate_agent_session(
    agent_name: str,
    model: str,
    num_llm_calls: int,
    num_tool_calls: int,
    num_steps: int,
    error_probability: float = 0.05,
    cost_multiplier: float = 1.0,
    base_time: float = None,
) -> list[dict]:
    """Generate a complete session with proper tree-structured parent_id.

    Tree structure:
        session.start                    (root)
        ├── agent.step [1]               (child of session.start)
        │   ├── llm.response             (child of step 1)
        │   └── tool.result              (child of step 1)
        ├── agent.step [2]               (child of session.start)
        │   ├── llm.response             (child of step 2)
        │   └── tool.result              (child of step 2)
        └── ...
        session.end                      (root, no parent)
    """
    base = base_time or time.time()
    session_id = _gen_session_id()
    events = []
    total_cost = 0
    total_tokens = 0
    error_count = 0
    t = base

    # ── Session start (root of the tree) ──
    session_start_id = _gen_event_id()
    events.append({
        "event_id": session_start_id,
        "event_type": "session.start",
        "session_id": session_id,
        "agent_name": agent_name,
        "timestamp": t,
        "tags": {"demo": True, "agent_type": agent_name},
    })
    t += random.uniform(0.01, 0.1)

    # Cost lookup
    cost_per_1k = {
        "gpt-4o": 0.0025, "gpt-4o-mini": 0.00015,
        "claude-3.5-sonnet": 0.003, "gemini-2.0-flash": 0.0001,
        "o3-mini": 0.0011,
    }

    # Distribute LLM & tool calls across steps
    actual_steps = max(num_steps, 1)
    llm_per_step = max(num_llm_calls // actual_steps, 1)
    tool_per_step = max(num_tool_calls // actual_steps, 0)
    leftover_llm = num_llm_calls - llm_per_step * actual_steps
    leftover_tool = num_tool_calls - tool_per_step * actual_steps

    for step_num in range(1, actual_steps + 1):
        step_id = _gen_event_id()
        step_start_time = t

        # How many sub-events in this step
        step_llm_count = llm_per_step + (1 if step_num <= leftover_llm else 0)
        step_tool_count = tool_per_step + (1 if step_num <= leftover_tool else 0)

        # ── Agent step (child of session.start) ──
        step_thought = random.choice([
            "Analyzing user query to determine intent",
            "Planning next action based on context",
            "Evaluating tool results for accuracy",
            "Deciding between multiple response strategies",
            "Checking if additional information is needed",
        ])
        step_decision = random.choice([
            "Call LLM for analysis",
            "Use web_search tool",
            "Respond to user directly",
            "Request clarification",
            "Execute code for verification",
        ])

        step_event = {
            "event_id": step_id,
            "event_type": "agent.step",
            "session_id": session_id,
            "agent_name": agent_name,
            "timestamp": t,
            "step_number": step_num,
            "thought": step_thought,
            "decision": step_decision,
            "parent_id": session_start_id,
        }
        events.append(step_event)
        t += random.uniform(0.01, 0.05)

        # ── LLM calls (children of this step) ──
        for _ in range(step_llm_count):
            is_error = random.random() < error_probability
            prompt = random.choice(PROMPTS)
            input_tokens = random.randint(50, 2000)
            output_tokens = random.randint(20, 1500)
            latency = random.uniform(200, 3000)

            base_cost = (input_tokens * cost_per_1k.get(model, 0.001) +
                        output_tokens * cost_per_1k.get(model, 0.002) * 4) / 1000
            cost = base_cost * cost_multiplier

            if is_error:
                events.append({
                    "event_id": _gen_event_id(),
                    "event_type": "llm.error",
                    "session_id": session_id,
                    "agent_name": agent_name,
                    "timestamp": t,
                    "model": model,
                    "provider": "openai" if "gpt" in model else "anthropic" if "claude" in model else "google",
                    "prompt": prompt,
                    "error_message": random.choice(ERROR_MESSAGES),
                    "error_type": "LLMError",
                    "success": False,
                    "latency_ms": latency,
                    "duration_ms": round(latency, 1),
                    "parent_id": step_id,
                })
                error_count += 1
            else:
                completion = random.choice(COMPLETIONS)
                events.append({
                    "event_id": _gen_event_id(),
                    "event_type": "llm.response",
                    "session_id": session_id,
                    "agent_name": agent_name,
                    "timestamp": t,
                    "model": model,
                    "provider": "openai" if "gpt" in model else "anthropic" if "claude" in model else "google",
                    "prompt": prompt,
                    "completion": completion,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "total_tokens": input_tokens + output_tokens,
                    "cost_usd": round(cost, 6),
                    "latency_ms": round(latency, 1),
                    "duration_ms": round(latency, 1),
                    "success": True,
                    "parent_id": step_id,
                })
                total_cost += cost
                total_tokens += input_tokens + output_tokens

            t += latency / 1000

        # ── Tool calls (children of this step) ──
        for _ in range(step_tool_count):
            tool = random.choice(TOOLS)
            is_tool_error = random.random() < (error_probability * 0.5)
            duration = random.uniform(10, 2000)

            if is_tool_error:
                events.append({
                    "event_id": _gen_event_id(),
                    "event_type": "tool.error",
                    "session_id": session_id,
                    "agent_name": agent_name,
                    "timestamp": t,
                    "tool_name": tool[0],
                    "tool_args": tool[1],
                    "error_message": f"Tool '{tool[0]}' failed: {random.choice(ERROR_MESSAGES)}",
                    "error_type": "ToolError",
                    "success": False,
                    "duration_ms": round(duration, 1),
                    "parent_id": step_id,
                })
                error_count += 1
            else:
                events.append({
                    "event_id": _gen_event_id(),
                    "event_type": "tool.result",
                    "session_id": session_id,
                    "agent_name": agent_name,
                    "timestamp": t,
                    "tool_name": tool[0],
                    "tool_args": tool[1],
                    "tool_result": tool[2],
                    "success": True,
                    "duration_ms": round(duration, 1),
                    "parent_id": step_id,
                })

            t += duration / 1000

        # ── Back-fill step duration_ms ──
        step_event["duration_ms"] = round((t - step_start_time) * 1000, 1)

    # ── Back-fill session.start duration_ms ──
    events[0]["duration_ms"] = round((t - base) * 1000, 1)

    # ── Session end (root, no parent — sibling of session.start) ──
    events.append({
        "event_id": _gen_event_id(),
        "event_type": "session.end",
        "session_id": session_id,
        "agent_name": agent_name,
        "timestamp": t,
        "success": error_count == 0,
        "meta": {
            "total_cost": round(total_cost, 6),
            "total_tokens": total_tokens,
            "llm_calls": num_llm_calls,
            "tool_calls": num_tool_calls,
            "steps": actual_steps,
            "errors": error_count,
        },
    })

    return events


def generate_demo_data() -> list[dict]:
    """Generate ~500 events across 5 agent types with realistic patterns."""
    all_events = []
    base_time = time.time() - 86400  # Start from 24h ago

    agent_configs = [
        # (name, model, sessions, llm_calls_per_sess, tool_calls, steps, error_prob, cost_mult)
        ("CustomerSupportBot", "gpt-4o-mini", 8, 4, 3, 3, 0.03, 1.0),
        ("ResearchAgent", "gpt-4o", 5, 6, 8, 5, 0.05, 1.0),
        ("CodeReviewAgent", "claude-3.5-sonnet", 6, 3, 2, 4, 0.15, 1.0),  # Higher error rate
        ("DataPipelineAgent", "gpt-4o", 4, 5, 4, 3, 0.02, 5.0),  # Cost spike!
        ("ChatBot", "gemini-2.0-flash", 12, 2, 1, 2, 0.02, 1.0),  # High volume, low cost
    ]

    for agent_name, model, num_sessions, llm_calls, tool_calls, steps, err_prob, cost_mult in agent_configs:
        for s in range(num_sessions):
            # Spread sessions across the 24h window
            session_time = base_time + (s * (86400 / num_sessions)) + random.uniform(0, 3600)
            session_events = generate_agent_session(
                agent_name=agent_name,
                model=model,
                num_llm_calls=llm_calls + random.randint(-1, 2),
                num_tool_calls=tool_calls + random.randint(-1, 1),
                num_steps=steps + random.randint(0, 2),
                error_probability=err_prob,
                cost_multiplier=cost_mult,
                base_time=session_time,
            )
            all_events.extend(session_events)

    # Sort by timestamp
    all_events.sort(key=lambda e: e.get("timestamp", 0))

    logger.info(f"Generated {len(all_events)} demo events across {sum(c[2] for c in agent_configs)} sessions")
    return all_events
