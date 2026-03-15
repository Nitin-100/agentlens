<h1 align="center">
  AgentLens
</h1>

<p align="center">
  <strong>Open-source observability for AI agents.</strong><br/>
  Trace every LLM call, tool use, and decision — in real-time.
</p>

<p align="center">
  <a href="https://github.com/agentlens/agentlens/actions"><img src="https://github.com/agentlens/agentlens/actions/workflows/ci.yml/badge.svg" alt="CI" /></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.9+-blue.svg" alt="Python 3.9+" /></a>
  <a href="https://opensource.org/licenses/MIT"><img src="https://img.shields.io/badge/License-MIT-green.svg" alt="License: MIT" /></a>
  <img src="https://img.shields.io/badge/tests-100%20passing-brightgreen.svg" alt="Tests: 100 passing" />
</p>

<p align="center">
  <a href="QUICKSTART.md">Quick Start</a> · <a href="#features">Features</a> · <a href="#how-it-works">Architecture</a> · <a href="#integrations">Integrations</a> · <a href="#comparison-vs-langfuse">vs Langfuse</a> · <a href="https://github.com/Nitin-100/agentlens/raw/main/Demo.mp4">Watch Demo</a>
</p>

---

<p align="center">
  <a href="https://github.com/Nitin-100/agentlens/raw/main/Demo.mp4">
    <img src="docs/demo-thumbnail.jpg" alt="Watch AgentLens Demo" width="720" />
    <br/>
    <sub>▶ Click to watch the full demo video</sub>
  </a>
</p>

---

## What is AgentLens?

AgentLens is a **self-hosted observability platform** for AI agents. It captures every LLM call, tool invocation, agent step, and error across any framework — OpenAI, Anthropic, Gemini, LangChain, CrewAI, LiteLLM, MCP — and shows it all in a real-time dashboard with trace trees, execution graphs, cost anomaly detection, and prompt diffs.

**3 lines to instrument your existing agent:**

```python
from agentlens import AgentLens, auto_patch

lens = AgentLens(server_url="http://localhost:8340")
auto_patch()  # auto-detects & patches OpenAI, Claude, Gemini, LangChain, CrewAI, LiteLLM, MCP

# Your existing code — zero changes needed
response = openai.chat.completions.create(model="gpt-4o", messages=[...])
# ^ model, tokens, cost, latency, response — all captured automatically
```

> **🚀 [Get started in 2 minutes → Quick Start Guide](QUICKSTART.md)**

---

## How It Works

```
  Your Agent Code
  ┌──────────────────────────────────────────────────────────┐
  │  OpenAI · Anthropic · Gemini · LangChain · CrewAI · MCP │
  └──────────────────────────┬───────────────────────────────┘
                             │  auto_patch()
                             ▼
                    ┌─────────────────┐
                    │  AgentLens SDK  │  ← zero dependencies
                    │  Batch · Retry  │
                    │  Circuit Breaker│
                    └────────┬────────┘
                             │  HTTP POST (batched every 2s)
                             ▼
  ┌──────────────────────────────────────────────────────────┐
  │               AgentLens Backend (FastAPI)                │
  │                                                          │
  │  ┌────────────┐  ┌──────────┐  ┌───────────────────┐    │
  │  │ Processors │  │ Database │  │    Exporters      │    │
  │  │ PII Redact │  │ SQLite   │  │ S3 · Kafka        │    │
  │  │ Sampling   │→ │ Postgres │→ │ Webhook · File    │    │
  │  │ Filtering  │  │ ClickHse │  └───────────────────┘    │
  │  └────────────┘  └──────────┘                            │
  │                                                          │
  │  OTEL /v1/traces · WebSocket /ws/live · REST API         │
  │  Cost Anomaly Detection · Prompt Diff · Alert Webhooks   │
  └──────────────────────────┬───────────────────────────────┘
                             │
                             ▼
  ┌──────────────────────────────────────────────────────────┐
  │                   Dashboard (React)                      │
  │  Overview · Sessions · Trace Tree · Agent Graph (DAG)   │
  │  Live Feed · Cost Anomalies · Alerts · Prompt Diff      │
  └──────────────────────────────────────────────────────────┘
```

**Data flow:** SDK intercepts LLM calls → batches events → Backend runs through processor pipeline (PII redaction, sampling, filtering) → stores in pluggable DB → forwards to exporters → Dashboard renders in real-time via WebSocket.

---

## Features

| | Feature | Description |
|---|---|---|
| 📡 | **Live Event Feed** | See every LLM call, tool use, and decision as it happens (WebSocket) |
| 🌳 | **Trace Tree** | Collapsible parent→child span hierarchy with timing waterfall |
| 🔗 | **Agent Graph** | Visual DAG of agent execution flow, color-coded by status |
| 🔍 | **Prompt Replay & Diff** | Click any LLM call to see prompt/completion, diff against similar prompts |
| 📉 | **Cost Anomaly Detection** | Zero-config — auto-flags when daily cost exceeds 2× rolling average |
| 💰 | **Cost Tracking** | Automatic pricing for 20+ models (GPT-4o, Claude 4, Gemini Pro, etc.) |
| 🔌 | **Plugin System** | Swap DB (SQLite → Postgres → ClickHouse), add exporters (S3, Kafka, Webhook) |
| 🛡️ | **PII Redaction** | Auto-scrubs emails, phones, SSNs, credit cards, API keys before storage |
| 🔐 | **Encryption at Rest** | AES-128-CBC + HMAC-SHA256 (Fernet) field-level encryption |
| 🔑 | **RBAC & API Keys** | Admin/Member/Viewer roles, key rotation with grace period |
| 📊 | **Prometheus Metrics** | Native `/metrics` endpoint — plug into Grafana |
| 🤖 | **MCP Native** | MCP client monitoring + MCP server for Claude Desktop |
| 🧪 | **One-Click Demo** | Load 500+ events across 5 agent types to explore instantly |
| 🌐 | **OTEL Ingestion** | Accept traces from any OpenTelemetry-compatible tool |
| ⚡ | **Zero Dependencies** | Core SDK uses only Python stdlib — no conflicts, ever |

---

## Integrations

Works with **any** AI agent framework. One `auto_patch()` call instruments everything:

| Framework | Method | What's Captured |
|---|---|---|
| **OpenAI** | `auto_patch()` | model, tokens, cost, latency, response |
| **Anthropic / Claude** | `auto_patch()` | model, tokens, tool_use blocks, cost |
| **Google Gemini / ADK** | `auto_patch()` | model, tokens, cost |
| **LangChain / LangGraph** | Callback handler | chains, tools, agents, retries |
| **CrewAI** | `auto_patch()` | kickoff, task execution, agent actions |
| **LiteLLM** (100+ providers) | `auto_patch()` | all providers via unified API |
| **MCP** | `auto_patch()` | tool calls, resource reads |
| **Any language** | REST API | POST JSON to `/api/v1/events` |

<details>
<summary><b>See framework-specific code examples</b></summary>

### OpenAI
```python
from agentlens import AgentLens
from agentlens.integrations.openai import patch_openai
lens = AgentLens(server_url="http://localhost:8340")
patch_openai(lens)
response = openai.chat.completions.create(model="gpt-4o", messages=[...])
```

### Anthropic / Claude
```python
from agentlens.integrations.anthropic import patch_anthropic
patch_anthropic(lens)
response = client.messages.create(model="claude-sonnet-4-20250514", messages=[...])
```

### Google Gemini
```python
from agentlens.integrations.google_adk import patch_gemini, patch_google_adk
patch_gemini(lens)
patch_google_adk(lens)
```

### LangChain
```python
from agentlens.integrations.langchain import AgentLensCallbackHandler
handler = AgentLensCallbackHandler(lens)
chain = LLMChain(llm=ChatOpenAI(), prompt=prompt, callbacks=[handler])
```

### CrewAI
```python
from agentlens.integrations.crewai import patch_crewai
patch_crewai(lens)
crew = Crew(agents=[analyst], tasks=[task])
result = crew.kickoff()
```

### LiteLLM
```python
from agentlens.integrations.litellm import patch_litellm
patch_litellm(lens)
response = litellm.completion(model="ollama/llama3", messages=[...])
```

### Custom / Manual
```python
lens.record_llm_call(model="my-model", prompt="...", response="...", tokens_in=100, tokens_out=50)
lens.record_tool_call(tool_name="my-tool", args={"key": "value"}, result="success", duration_ms=150)
lens.record_step(step_name="process", data={"status": "done"})
```
</details>

---

## Multi-Language SDKs

| Language | Install | Status |
|---|---|---|
| Python | `pip install agentlens` | ✅ Full SDK + CLI + auto-patch |
| TypeScript | `npm install @agentlens/sdk` | ✅ Full types, OpenAI/Anthropic patch |
| JavaScript | `sdk/javascript/agentlens.js` | ✅ Node.js + Browser |
| Go | `sdk/go/agentlens.go` | ✅ Native SDK |
| Java | `sdk/java/` | ✅ Java 11+, zero deps |
| Any language | REST API | ✅ cURL examples in `sdk/rest-api/` |
| OpenTelemetry | `POST /v1/traces` | ✅ OTLP JSON ingestion |

<details>
<summary><b>See examples for each language</b></summary>

### TypeScript
```typescript
import { AgentLens, patchOpenAI } from '@agentlens/sdk';
const lens = new AgentLens({ serverUrl: 'http://localhost:8340', agentName: 'my-agent' });
const openai = new OpenAI();
patchOpenAI(openai, lens);
// All calls auto-tracked
```

### Go
```go
lens := agentlens.New("http://localhost:8340", "al_your_key")
defer lens.Shutdown()
sess := lens.StartSession("my-agent")
lens.TrackLLMCall(agentlens.LLMEvent{Model: "gpt-4o", Prompt: "Hello"})
lens.EndSession(sess, true, nil)
```

### Java
```java
AgentLens lens = new AgentLens("http://localhost:8340", "al_your_key");
String session = lens.startSession("my-agent");
lens.trackLLMCall("gpt-4o", "openai", "Hello", "Hi!", 5, 3, 0.001, 200);
lens.endSession(session, true, Map.of());
lens.shutdown();
```

### cURL (any language)
```bash
curl -X POST http://localhost:8340/api/v1/events \
  -H "Content-Type: application/json" \
  -d '{"events": [{"event_type": "llm.response", "model": "gpt-4o", "prompt": "Hello"}]}'
```
</details>

---

## Plugin System

Extend every layer — databases, exporters, and event processors.

```
Events → [Processors: PII · Sample · Filter · Enrich] → [Database] → [Exporters: S3 · Kafka · Webhook · File]
```

<details>
<summary><b>Database plugins — swap storage without code changes</b></summary>

```python
from agentlens.plugins import PluginRegistry
from agentlens.builtin_plugins import PostgreSQLPlugin, ClickHousePlugin

registry = PluginRegistry.get_instance()

# PostgreSQL for production
registry.register_database(PostgreSQLPlugin(dsn="postgresql://user:pass@localhost:5432/agentlens"))

# ClickHouse for analytics at scale
registry.register_database(ClickHousePlugin(url="http://localhost:8123", database="agentlens"))
```

| Plugin | Best For | Scale |
|---|---|---|
| SQLite (built-in) | Development | < 100K events/day |
| PostgreSQL | Production OLTP | < 10M events/day |
| ClickHouse | Analytics, massive scale | 100M+ events/day |
</details>

<details>
<summary><b>Exporter plugins — send events to external systems</b></summary>

```python
from agentlens.builtin_plugins import S3Exporter, WebhookExporter, KafkaExporter, FileExporter

registry.register_exporter(S3Exporter(bucket="my-data", prefix="events/"))
registry.register_exporter(WebhookExporter(url="https://hooks.slack.com/...", filter_types=["error"]))
registry.register_exporter(KafkaExporter(bootstrap_servers="localhost:9092", topic="agentlens.events"))
registry.register_exporter(FileExporter(directory="./logs", max_file_mb=100))
```
</details>

<details>
<summary><b>Event processors — transform events before storage</b></summary>

```python
from agentlens.builtin_plugins import PIIRedactor, SamplingProcessor, FilterProcessor, EnrichmentProcessor

registry.register_processor(PIIRedactor())                                    # scrub emails, phones, SSNs
registry.register_processor(SamplingProcessor(rate=0.1))                      # keep 10% (always keeps errors)
registry.register_processor(FilterProcessor(drop_types=["custom.debug"]))     # drop noisy events
registry.register_processor(EnrichmentProcessor(metadata={"env": "prod"}))    # tag every event
```
</details>

<details>
<summary><b>Event hooks & custom plugins</b></summary>

```python
@registry.on("error")
def on_error(event):
    print(f"Error in {event['agent_name']}: {event.get('error_type')}")

@registry.on_async("session.end")
async def on_session_end(event):
    if event.get("total_cost_usd", 0) > 5.0:
        await send_alert(f"Expensive session: ${event['total_cost_usd']:.2f}")
```

Build your own by implementing `DatabasePlugin`, `ExporterPlugin`, or `EventProcessor` base classes.
</details>

---

## MCP Support

First-class Model Context Protocol support — both as a client monitor and as an MCP server.

<details>
<summary><b>MCP client monitoring</b></summary>

```python
from agentlens.integrations.mcp import patch_mcp
patch_mcp(lens)

async with ClientSession(read, write) as session:
    result = await session.call_tool("web_search", {"query": "AI agents"})
    # ^ automatically captured
```
</details>

<details>
<summary><b>MCP server — query AgentLens from Claude Desktop</b></summary>

Add to `claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "agentlens": {
      "command": "agentlens-mcp",
      "args": ["--server-url", "http://localhost:8340"]
    }
  }
}
```

**Resources:** `agentlens://sessions` · `agentlens://analytics` · `agentlens://errors` · `agentlens://health`

**Tools:** `query_sessions` · `query_analytics` · `query_errors` · `get_session_detail` · `create_alert_rule` · `get_system_health`

> *"Show me all failed sessions from research-agent in the last 24 hours"*
</details>

---

## Security

| Capability | Details |
|---|---|
| **Encryption at rest** | AES-128-CBC + HMAC-SHA256 (Fernet) — prompts, completions, tool args, errors |
| **TLS** | Built-in uvicorn SSL, self-signed cert generator, no nginx needed |
| **RBAC** | Admin / Member / Viewer (14/7/4 permissions), API key scoping per project |
| **API key rotation** | Configurable grace period, old key auto-expires |
| **PII redaction** | Emails, phones, SSNs, credit cards, API keys — auto-scrubbed |
| **Audit logging** | Every admin action: timestamp, IP, user-agent |
| **Data retention** | Per-project policies, automated background purge |
| **Multi-tenancy** | Project-level data isolation |
| **Self-hosted** | Your data never leaves your infrastructure |

<details>
<summary><b>Configuration examples</b></summary>

```bash
# Encryption — auto-generates key on first start
export AGENTLENS_ENCRYPTION_KEY="your-base64-fernet-key"

# TLS
cd backend && python tls.py --generate-self-signed
export AGENTLENS_TLS_CERT=agentlens-cert.pem
export AGENTLENS_TLS_KEY=agentlens-key.pem

# Key rotation (24h grace period)
curl -X POST http://localhost:8340/api/v1/keys/{key_id}/rotate \
  -H "Authorization: Bearer al_admin_key" \
  -d '{"grace_period_hours": 24}'

# Data retention — 90 days
curl -X PUT http://localhost:8340/api/v1/retention \
  -H "Authorization: Bearer al_admin_key" \
  -d '{"retention_days": 90, "delete_events": true, "delete_sessions": true}'
```
</details>

---

## Deployment

<details>
<summary><b>Docker Compose (recommended)</b></summary>

```bash
git clone https://github.com/Nitin-100/agentlens.git
cd agentlens
docker compose up -d
# Dashboard → http://localhost:5173
# API docs → http://localhost:8340/docs
```
</details>

<details>
<summary><b>Manual setup</b></summary>

```bash
# Terminal 1 — Backend
cd backend && pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8340

# Terminal 2 — Dashboard
cd dashboard && npm install && npm run dev

# Terminal 3 — Your agent
pip install agentlens && python your_agent.py
```
</details>

<details>
<summary><b>Kubernetes (Helm)</b></summary>

```bash
helm install agentlens ./helm/agentlens \
  --set image.tag=0.3.0 \
  --set persistence.enabled=true \
  --set prometheus.serviceMonitor.enabled=true
```
</details>

<details>
<summary><b>Production with PostgreSQL</b></summary>

```yaml
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_DB: agentlens
      POSTGRES_USER: agentlens
      POSTGRES_PASSWORD: secret
  backend:
    build: ./backend
    environment:
      - DATABASE_URL=postgresql://agentlens:secret@postgres:5432/agentlens
```
</details>

---

## Comparison vs Langfuse

| Feature | AgentLens | Langfuse |
|---|---|---|
| Nested trace tree | ✅ | ✅ |
| OTEL ingestion | ✅ | ✅ |
| Self-hosted | ✅ | ✅ |
| Multi-language SDKs | ✅ | ✅ |
| Cost tracking | ✅ Auto | ✅ Auto |
| RBAC | ✅ | ✅ |
| **Cost anomaly detection** | **✅ Zero-config** | ❌ |
| **PII redaction (built-in)** | **✅** | ❌ |
| **Encryption at rest** | **✅** | ❌ |
| **Plugin system (DB/export)** | **✅** | ❌ |
| **MCP native** | **✅** | ❌ |
| **Agent graph (DAG)** | **✅** | ❌ |
| **CLI verify tool** | **✅** | ❌ |
| **Zero SDK dependencies** | **✅** | ❌ |
| **Prometheus /metrics** | **✅** | ❌ |
| Prompt management | ❌ | ✅ |
| LLM-as-judge evals | ❌ | ✅ |
| Datasets & experiments | ❌ | ✅ |
| Maturity & community | Early | Established |

**Honest take:** Langfuse is more mature with a larger ecosystem. AgentLens differentiates on **developer experience** (zero deps, CLI verify, one-click demo), **security** (encryption, PII redaction, TLS built-in), and **unique features** (cost anomaly auto-detection, plugin architecture, MCP-native, agent graph). See [`docs/migrating-from-langfuse.md`](docs/migrating-from-langfuse.md) for a migration guide.

---

## API Reference

<details>
<summary><b>All REST endpoints (35+)</b></summary>

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/v1/events` | Ingest event batch |
| `GET` | `/api/v1/sessions` | List sessions (`?agent=`, `?limit=`, `?offset=`) |
| `GET` | `/api/v1/sessions/{id}` | Session detail with timeline |
| `GET` | `/api/v1/sessions/{id}/graph` | Execution graph (DAG) |
| `GET` | `/api/v1/events` | List events (`?type=`, `?session_id=`) |
| `GET` | `/api/v1/events/{id}/detail` | Event detail + similar prompts |
| `GET` | `/api/v1/events/{id}/diff/{other_id}` | Prompt diff |
| `GET` | `/api/v1/analytics` | Aggregated stats |
| `GET` | `/api/v1/live` | Last 60s of events |
| `GET` | `/api/v1/traces/{trace_id}` | Nested trace tree |
| `POST` | `/api/v1/alerts` | Create alert rule |
| `GET` | `/api/v1/alerts` | List alerts |
| `DELETE` | `/api/v1/alerts/{id}` | Delete alert |
| `GET` | `/api/v1/anomalies` | Cost anomalies |
| `GET` | `/api/v1/anomalies/trends` | Daily cost trends |
| `POST` | `/api/v1/anomalies/{id}/acknowledge` | Ack anomaly |
| `POST` | `/api/v1/keys` | Create API key |
| `POST` | `/api/v1/keys/{id}/rotate` | Rotate key |
| `POST` | `/api/v1/projects` | Create project |
| `GET/PUT` | `/api/v1/retention` | Data retention policy |
| `POST` | `/v1/traces` | OTEL OTLP ingestion |
| `POST` | `/api/v1/demo/load` | Load demo data |
| `GET` | `/api/health` | Health check |
| `WS` | `/ws/live` | WebSocket live stream |
| `GET` | `/metrics` | Prometheus metrics |

Full interactive docs at `http://localhost:8340/docs`
</details>

<details>
<summary><b>SDK configuration</b></summary>

```python
lens = AgentLens(
    server_url="http://localhost:8340",
    project_id="my-project",
    api_key="your-api-key",
    flush_interval=2.0,           # batch flush (seconds)
    max_buffer_size=10000,        # max events in memory
    sampling_rate=1.0,            # 1.0 = all, 0.1 = 10%
    max_retries=3,
    circuit_breaker_threshold=5,
    circuit_breaker_timeout=60,
)
```

| Env Variable | Default | Description |
|---|---|---|
| `AGENTLENS_SERVER_URL` | `http://localhost:8340` | Backend URL |
| `AGENTLENS_API_KEY` | — | Auth key |
| `AGENTLENS_SAMPLING_RATE` | `1.0` | Event sampling (0.0–1.0) |
| `AGENTLENS_FLUSH_INTERVAL` | `2.0` | Batch interval (seconds) |
</details>

---

## Examples

```python
# Basic — instrument an existing agent
from agentlens import AgentLens, monitor, auto_patch
lens = AgentLens(server_url="http://localhost:8340")
auto_patch()

@monitor("my-agent")
def run(task):
    return openai.chat.completions.create(model="gpt-4o", messages=[{"role": "user", "content": task}])

run("Summarize the latest AI news")
```

<details>
<summary><b>Multi-agent system</b></summary>

```python
@monitor("orchestrator")
def orchestrate(task):
    plan = planner(task)
    results = [worker(step) for step in plan]
    return synthesizer(results)

@monitor("planner")
def planner(task):
    return openai.chat.completions.create(model="gpt-4o", messages=[...])

@monitor("worker")
def worker(step):
    return anthropic.messages.create(model="claude-sonnet-4-20250514", messages=[...])
```
</details>

<details>
<summary><b>Production setup with plugins</b></summary>

```python
from agentlens import AgentLens, auto_patch, PluginRegistry
from agentlens.builtin_plugins import PostgreSQLPlugin, S3Exporter, WebhookExporter, PIIRedactor, SamplingProcessor

lens = AgentLens(server_url="http://localhost:8340")
auto_patch()

registry = PluginRegistry.get_instance()
registry.register_database(PostgreSQLPlugin(dsn="postgresql://..."))
registry.register_exporter(WebhookExporter(url="https://hooks.slack.com/...", filter_types=["error"]))
registry.register_exporter(S3Exporter(bucket="agent-data"))
registry.register_processor(PIIRedactor())
registry.register_processor(SamplingProcessor(rate=0.1))
```
</details>

---

## Roadmap

| Feature | Status |
|---|---|
| User/session grouping (`set_user()`) | ✅ Shipped |
| Prometheus `/metrics` endpoint | ✅ Shipped |
| Grafana dashboard template | ✅ Shipped |
| `agentlens demo` CLI | ✅ Shipped |
| Helm chart for Kubernetes | ✅ Shipped |
| Langfuse migration guide | ✅ Shipped |
| 100 tests passing | ✅ Shipped |
| Prompt management | 🔴 Not planned (use Langfuse/PromptLayer) |
| LLM-as-judge evals | 🔴 Not planned (use Braintrust) |

---

## Tech Stack

| Component | Tech | Why |
|---|---|---|
| SDK | Python (zero deps) | Works everywhere |
| Backend | FastAPI + async SQLite | Fast, modern |
| Dashboard | React 18 + Vite | Lightweight, instant HMR |
| Database | SQLite → Postgres → ClickHouse | Scale from laptop to cloud |
| Deploy | Docker Compose / Helm | One command |

---

## Contributing

```bash
git clone https://github.com/Nitin-100/agentlens.git && cd agentlens
cd backend && pip install -r requirements.txt        # Backend
cd dashboard && npm install && npm run dev            # Dashboard
cd sdk/python && pip install -e ".[dev]"              # SDK
pytest                                                # Tests
```

---

## License

MIT — use it however you want.

---

<p align="center">
  <strong>Built for developers who ship AI agents and need to know what they're doing.</strong>
  <br/><br/>
  <a href="QUICKSTART.md">🚀 Quick Start</a> · <a href="https://github.com/Nitin-100/agentlens/issues">Report Bug</a> · <a href="https://github.com/Nitin-100/agentlens/issues">Request Feature</a>
</p>
