# Migrating from Langfuse to AgentLens

This guide helps you migrate from Langfuse to AgentLens with minimal friction.

---

## Why Migrate?

| Feature | Langfuse | AgentLens |
|---------|----------|-----------|
| Self-hosted | ✅ (Docker + Postgres) | ✅ (single binary, SQLite) |
| Setup complexity | ~15 min (Docker Compose) | ~2 min (pip install + run) |
| Pricing model | Freemium / Cloud | 100% free, MIT license |
| Agent DAG visualization | ❌ | ✅ Built-in |
| Cost anomaly detection | ❌ | ✅ Z-score + alerts |
| Prompt replay / diff | ❌ | ✅ Side-by-side diff |
| OTEL ingestion | ❌ | ✅ OTLP JSON |
| Nested trace tree | ✅ | ✅ Waterfall view |
| Prometheus `/metrics` | ❌ | ✅ Native |
| Helm chart | Community | ✅ Official |
| SDK overhead | Higher (network calls) | <1ms (async batching) |

---

## Step 1: Install AgentLens

```bash
pip install agentlens
```

Or run the backend directly:
```bash
git clone https://github.com/user/agentlens.git
cd agentlens/backend
pip install -r requirements.txt
python -m uvicorn main:app --port 8340
```

---

## Step 2: Replace SDK Initialization

### Langfuse (before)
```python
from langfuse import Langfuse

langfuse = Langfuse(
    public_key="pk-...",
    secret_key="sk-...",
    host="https://cloud.langfuse.com",
)
```

### AgentLens (after)
```python
from agentlens import AgentLens

lens = AgentLens(
    server_url="http://localhost:8340",
    project="my-project",
)
```

---

## Step 3: Replace Tracing Calls

### Langfuse traces → AgentLens sessions

| Langfuse | AgentLens |
|----------|-----------|
| `langfuse.trace(name="my-agent")` | `lens.start_session(agent_name="my-agent")` |
| `trace.update(output="...")` | `lens.end_session(output_data="...")` |

**Langfuse:**
```python
trace = langfuse.trace(name="my-agent", user_id="user_123")
# ... run agent ...
trace.update(output=result)
```

**AgentLens:**
```python
lens.set_user("user_123")
session = lens.start_session(agent_name="my-agent")
# ... run agent ...
lens.end_session(success=True, output_data=result)
```

### LLM calls (generations)

| Langfuse | AgentLens |
|----------|-----------|
| `trace.generation(name="gpt-4", ...)` | `lens.record_llm_call(model="gpt-4", ...)` |

**Langfuse:**
```python
generation = trace.generation(
    name="chat",
    model="gpt-4",
    input=[{"role": "user", "content": "Hello"}],
    output="Hi there!",
    usage={"input": 10, "output": 5},
)
```

**AgentLens:**
```python
lens.record_llm_call(
    model="gpt-4",
    prompt=[{"role": "user", "content": "Hello"}],
    completion="Hi there!",
    input_tokens=10,
    output_tokens=5,
    latency_ms=350,
)
```

### Tool calls (spans)

| Langfuse | AgentLens |
|----------|-----------|
| `trace.span(name="search", ...)` | `lens.record_tool_call(tool_name="search", ...)` |

**Langfuse:**
```python
span = trace.span(name="web_search", input={"q": "weather"})
span.update(output={"temp": 72})
span.end()
```

**AgentLens:**
```python
lens.record_tool_call(
    tool_name="web_search",
    args={"q": "weather"},
    result={"temp": 72},
    duration_ms=120,
)
```

---

## Step 4: Replace Decorators

### Langfuse `@observe` → AgentLens `@monitor`

**Langfuse:**
```python
from langfuse.decorators import observe

@observe()
def my_agent(query):
    ...
```

**AgentLens:**
```python
@lens.monitor(agent_name="my-agent")
def my_agent(query):
    ...
```

---

## Step 5: Framework Integrations

### OpenAI

**Langfuse:**
```python
from langfuse.openai import openai  # patched import
```

**AgentLens:**
```python
from agentlens.integrations.openai import patch_openai
patch_openai()
# Use openai normally — all calls auto-recorded
```

### LangChain

**Langfuse:**
```python
from langfuse.callback import CallbackHandler
handler = CallbackHandler()
chain.invoke(input, config={"callbacks": [handler]})
```

**AgentLens:**
```python
from agentlens.integrations.langchain import AgentLensCallback
callback = AgentLensCallback()
chain.invoke(input, config={"callbacks": [callback]})
```

---

## Step 6: Dashboard Access

| Langfuse | AgentLens |
|----------|-----------|
| `https://cloud.langfuse.com` | `http://localhost:8340/dashboard` |
| Hosted Cloud required for full features | Fully self-hosted, all features |

---

## Step 7: Verify Installation

```bash
agentlens verify http://localhost:8340
```

Expected output:
```
🔭 AgentLens Verify — v0.3.0
   Server: http://localhost:8340

  ✅ Server Reachable        OK                                       (5ms)
  ✅ Health Endpoint          OK                                       (3ms)
  ✅ Events Writable          OK                                       (12ms)
  ✅ Sessions Readable        OK                                       (4ms)
  ✅ Analytics Working        OK                                       (6ms)
  ✅ OTEL Endpoint            OK                                       (8ms)
  ✅ WebSocket Available      OK                                       (3ms)

  🎉 All 7 checks passed! Your AgentLens installation is ready.
```

---

## API Compatibility Reference

| Langfuse API | AgentLens API |
|-------------|---------------|
| `POST /api/public/ingestion` | `POST /api/v1/events` |
| `GET /api/public/traces` | `GET /api/v1/sessions` |
| `GET /api/public/traces/:id` | `GET /api/v1/sessions/:id` |
| `GET /api/public/observations` | `GET /api/v1/events` |
| — | `GET /api/v1/traces/:id` (nested tree) |
| — | `GET /api/v1/analytics` |
| — | `GET /api/v1/anomalies` |
| — | `GET /api/v1/sessions/:id/graph` (DAG) |
| — | `GET /metrics` (Prometheus) |
| — | `POST /api/v1/otel/v1/traces` (OTEL) |
| — | `POST /api/v1/demo/load` |

---

## Need Help?

- Run `agentlens verify` to diagnose connectivity
- Run `agentlens demo` to load sample data
- Check [README.md](../README.md) for full documentation
- Open an issue on GitHub
