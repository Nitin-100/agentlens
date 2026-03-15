<p align="center">
  <h1 align="center">AgentLens</h1>
  <p align="center"><strong>AI Agent Observability — See what your agents actually do.</strong></p>
  <p align="center">
    <a href="#quick-start">Quick Start</a> •
    <a href="#features">Features</a> •
    <a href="#integrations">Integrations</a> •
    <a href="#opentelemetry-ingestion">OpenTelemetry</a> •
    <a href="#plugin-system">Plugins</a> •
    <a href="#mcp-support">MCP</a> •
    <a href="#cli--agentlens-verify">CLI</a> •
    <a href="#comparison">vs Langfuse</a> •
    <a href="#roadmap">Roadmap</a> •
    <a href="#api-reference">API</a>
  </p>
</p>

---

Monitor every LLM call, tool use, decision, and error across **any AI agent framework** — in real-time. Self-hosted. Open-source. Zero mandatory dependencies.

**What's in the box:** OTEL ingestion with `gen_ai.*` mapping, nested trace tree/waterfall, agent graph (DAG), prompt replay with diff, zero-config cost anomaly detection, user/session grouping with `set_user()`, Prometheus `/metrics` endpoint, Grafana dashboard template, TypeScript + Python + Go + Java + JS SDKs, field-level encryption at rest (Fernet), built-in TLS, RBAC with key rotation, data retention auto-purge, PII redaction, MCP-native, plugin architecture (Postgres/ClickHouse/S3/Kafka), `agentlens verify` + `agentlens demo` CLI, Helm chart for K8s, Langfuse migration guide, one-click demo data, and 100 tests passing.

[![CI](https://github.com/agentlens/agentlens/actions/workflows/ci.yml/badge.svg)](https://github.com/agentlens/agentlens/actions)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![Tests: 100 passing](https://img.shields.io/badge/tests-100%20passing-brightgreen.svg)]()

```python
from agentlens import AgentLens, auto_patch

lens = AgentLens(server_url="http://localhost:8340")
auto_patch()  # auto-detects OpenAI, Claude, Gemini, LangChain, CrewAI, LiteLLM, MCP

# Your existing agent code — no changes needed
response = openai.chat.completions.create(model="gpt-4o", messages=[...])
# ^ automatically captured: model, tokens, cost, latency, response
```

```bash
# Verify your installation in one command
agentlens verify http://localhost:8340

# ✅ Server Reachable       HTTP 200                (12ms)
# ✅ Health Endpoint         status=healthy, v=0.3.0 (8ms)
# ✅ Event Ingestion         inserted=1              (15ms)
# ✅ OTEL Endpoint           HTTP 200, inserted=0    (10ms)
# 🎉 All 7 checks passed!
```

<p align="center">
  <a href="https://github.com/Nitin-100/agentlens/raw/main/Demo.mp4">
    <img src="https://raw.githubusercontent.com/Nitin-100/agentlens/main/docs/demo-thumbnail.jpg" alt="Watch AgentLens Demo" width="720" />
    <br/>
    <sub>▶ Click to watch the demo</sub>
  </a>
</p>

---

## The Problem

You deploy an AI agent. It calls GPT-4, invokes tools, makes multi-step decisions, chains with other agents. But you have **zero visibility** into:

- What did it decide at step 3 and why?
- How much did this conversation cost?  
- Why did it fail for that one user?
- Which tool is the performance bottleneck?
- Is it hallucinating or staying in bounds?
- Did the MCP tool call succeed?

LangSmith tracks tokens. Helicone tracks API calls. **AgentLens tracks agent behavior.**

---

## Who Benefits

| Role | Value |
|---|---|
| **AI Agent Developers** | Debug agents in dev — see every LLM call, tool use, and decision in a timeline view |
| **ML/AI Engineers** | Compare model performance, track cost per agent, identify prompt optimization targets |
| **DevOps / Platform Teams** | Monitor production agents, set up alerts on error rates and cost spikes, self-host on your infra |
| **Startup CTOs** | Get visibility into AI spend, track reliability metrics for investor reports, avoid bill shock |
| **Consultants / Freelancers** | Prove agent performance to clients with dashboards and session replays |
| **Open Source AI Projects** | Add production-grade observability with zero dependencies and 3 lines of code |

---

## Quick Start

### Option 1: Docker (recommended)

```bash
git clone https://github.com/agentlens/agentlens.git
cd agentlens
docker compose up -d
# Dashboard: http://localhost:5173
# API: http://localhost:8340/docs
```

### Option 2: Manual

```bash
# Terminal 1 — Backend
cd backend
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8340

# Terminal 2 — Dashboard
cd dashboard
npm install
npm run dev

# Terminal 3 — Your agent
pip install agentlens
python your_agent.py

# Verify everything works
agentlens verify http://localhost:8340
```

### Option 3: SDK only (no server)

```python
from agentlens import AgentLens

# Runs with local file logging — no server needed
lens = AgentLens(server_url=None, fallback_to_file=True)
```

---

## Features

### Real-time Dashboard
- **Live event feed** — see every LLM call, tool use, and decision as it happens via WebSocket
- **Nested trace tree** — collapsible tree/waterfall view showing parent→child span hierarchy with timing bars
- **Agent graph (DAG)** — visual node-edge graph of agent execution flow, color-coded by status
- **Prompt replay & diff** — click any LLM call to see prompt/completion side-by-side, diff against similar prompts
- **Cost anomaly detection** — zero-config automatic detection when daily cost exceeds 2× rolling average, with 30-day trend charts
- **Cost tracking** — automatic cost calculation for 20+ models (GPT-4o, Claude 4, Gemini Pro, etc.)
- **Error monitoring** — catch failures, stack traces, and error patterns before they compound
- **Alert system** — configure webhooks for cost spikes, error bursts, slow agents
- **One-click demo data** — load 500+ realistic events across 5 agent types to explore the dashboard instantly

### Agent-Level Instrumentation

```python
from agentlens import AgentLens, monitor, tool, step

lens = AgentLens(server_url="http://localhost:8340")

@monitor("research-agent")
async def research_agent(topic):
    results = await search(topic)
    analysis = await analyze(results)
    return analysis

@tool("web-search")
async def search(query):
    return await httpx.get(f"https://api.search.com/?q={query}")

@step("analyze-results")
def analyze(results):
    # Your logic — duration, success/failure, args all captured
    return summary
```

### Zero-Dependency SDK
The core SDK uses only Python standard library. No `requests`, no `httpx`, no `pydantic`. Just `urllib`, `json`, `threading`. Install extra integrations only when you need them:

```bash
pip install agentlens                          # Core (zero deps)
pip install agentlens[openai]                  # + OpenAI integration
pip install agentlens[postgresql,s3]           # + PostgreSQL + S3
pip install agentlens[all]                     # Everything
```

### Production-Grade Reliability
- **RBAC** — Role-based access control with admin/member/viewer roles, API key scoping per project, audit logging
- **Multi-tenancy** — Project-level data isolation, per-project API keys, per-project rate limits
- **Encryption at rest** — AES-128-CBC + HMAC-SHA256 (Fernet) field-level encryption for sensitive data (prompts, completions, tool args, errors)
- **TLS support** — Built-in HTTPS via uvicorn SSL, no nginx/Caddy required. Self-signed cert generation included
- **Data retention policies** — Per-project configurable auto-purge (default: 90 days), background cleanup, purge history/audit
- **Key rotation** — Rotate API keys with configurable grace period, old key auto-expires after grace window
- **Security headers** — X-Frame-Options, CSP, HSTS, XSS Protection, no-cache on all responses
- **Circuit breaker** — stops hammering a down server (CLOSED → OPEN → HALF_OPEN)
- **Exponential backoff retry** — 3 attempts with jitter
- **Dead Letter Queue** — failed events saved to disk, replayed on recovery
- **Graceful shutdown** — drains buffered events on process exit
- **Sampling** — configurable event sampling rate for high-throughput agents
- **Rate limiting** — backend enforces token-bucket rate limiting (100 req/s default)
- **PII Redaction** — Auto-scrubs emails, phones, SSNs, credit cards, API keys before storage

### OpenTelemetry Ingestion

AgentLens natively accepts **OTLP JSON** traces over HTTP. Point any OTEL exporter at AgentLens:

```bash
# Configure any OTEL-compatible tool to export to AgentLens
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:8340
export OTEL_EXPORTER_OTLP_PROTOCOL=http/json

# Works with: OpenLLMetry, Traceloop, Arize, any OTEL SDK
```

AgentLens maps `gen_ai.*` semantic conventions to native events — model, tokens, cost, parent spans all preserved.

### CLI — `agentlens verify`

Verify your AgentLens installation with a single command:

```bash
pip install agentlens
agentlens verify                            # checks localhost:8340
agentlens verify http://your-server:8340    # custom URL
agentlens verify --json                     # machine-readable output
```

Runs 7 connectivity checks: server reachable, health endpoint, event ingestion, sessions API, analytics API, OTEL endpoint, WebSocket.

### Multi-Language SDK Support

AgentLens works with **any programming language** via its REST API. Native SDKs provided for:

| Language | SDK | Status |
|----------|-----|--------|
| Python | `pip install agentlens` | ✅ Full SDK with auto-patching, CLI |
| TypeScript | `npm install @agentlens/sdk` | ✅ Full types, OpenAI/Anthropic auto-patch |
| JavaScript | `sdk/javascript/agentlens.js` | ✅ Native SDK (Node.js + Browser) |
| Go | `sdk/go/agentlens.go` | ✅ Native SDK |
| Java | `sdk/java/` | ✅ Native SDK (Java 11+, zero deps) |
| Ruby / Rust / C# / Any | REST API (`/api/v1/events`) | ✅ cURL examples provided |
| OpenTelemetry | `POST /v1/traces` | ✅ OTLP JSON ingestion |

For any language not listed, just POST JSON to `/api/v1/events` — see `sdk/rest-api/examples.sh`.

---

## Integrations

AgentLens works with **any** AI agent framework. One `auto_patch()` call detects and instruments all installed frameworks.

### Auto-Patch (Recommended)

```python
from agentlens import AgentLens, auto_patch

lens = AgentLens(server_url="http://localhost:8340")
auto_patch()
# Automatically patches: OpenAI, Anthropic, Gemini, LangChain, CrewAI, LiteLLM, MCP
```

### Framework-Specific

<details>
<summary><b>OpenAI</b></summary>

```python
from agentlens import AgentLens
from agentlens.integrations.openai import patch_openai

lens = AgentLens(server_url="http://localhost:8340")
patch_openai(lens)

# All OpenAI calls auto-tracked — sync and async
response = openai.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Hello"}]
)
```
Captures: model, tokens (prompt + completion), estimated cost, latency, full response.
</details>

<details>
<summary><b>Anthropic / Claude</b></summary>

```python
from agentlens.integrations.anthropic import patch_anthropic

patch_anthropic(lens)

# Claude calls auto-tracked — including tool_use blocks
response = client.messages.create(
    model="claude-sonnet-4-20250514",
    messages=[{"role": "user", "content": "Analyze this data"}]
)
```
Captures: model, input/output tokens, stop_reason, tool_use blocks, cost.
</details>

<details>
<summary><b>Google Gemini / ADK</b></summary>

```python
from agentlens.integrations.google_adk import patch_gemini, patch_google_adk

patch_gemini(lens)       # Google Generative AI
patch_google_adk(lens)   # Google Agent Development Kit

model = genai.GenerativeModel("gemini-pro")
response = model.generate_content("Hello")
```
</details>

<details>
<summary><b>LangChain / LangGraph</b></summary>

```python
from agentlens.integrations.langchain import AgentLensCallbackHandler

handler = AgentLensCallbackHandler(lens)

# Pass as callback to any LangChain component
chain = LLMChain(llm=ChatOpenAI(), prompt=prompt, callbacks=[handler])
result = chain.run("Analyze this")
```
Captures: on_llm_start/end, on_tool_start/end, on_chain_start/end, on_agent_action/finish, on_retry.
</details>

<details>
<summary><b>CrewAI</b></summary>

```python
from agentlens.integrations.crewai import patch_crewai

patch_crewai(lens)

# Crew.kickoff(), Agent.execute_task(), Task.execute_sync() all tracked
crew = Crew(agents=[analyst], tasks=[task])
result = crew.kickoff()
```
</details>

<details>
<summary><b>LiteLLM (100+ providers)</b></summary>

```python
from agentlens.integrations.litellm import patch_litellm

patch_litellm(lens)

# Track calls to any of 100+ providers through LiteLLM
import litellm
response = litellm.completion(model="gpt-4o", messages=[...])
response = litellm.completion(model="claude-sonnet-4-20250514", messages=[...])
response = litellm.completion(model="ollama/llama3", messages=[...])
```
</details>

<details>
<summary><b>MCP (Model Context Protocol)</b></summary>

```python
from agentlens.integrations.mcp import patch_mcp

patch_mcp(lens)

# All MCP tool calls and resource reads are tracked
async with ClientSession(read, write) as session:
    result = await session.call_tool("search", {"query": "hello"})
```
See [MCP Support](#mcp-support) for the full MCP server integration.
</details>

<details>
<summary><b>Custom / Any Framework</b></summary>

```python
from agentlens import AgentLens

lens = AgentLens(server_url="http://localhost:8340")

# Manual recording for any framework
lens.record_llm_call(model="my-model", prompt="...", response="...",
                     tokens_in=100, tokens_out=50)
lens.record_tool_call(tool_name="my-tool", args={"key": "value"},
                      result="success", duration_ms=150)
lens.record_step(step_name="process", data={"status": "done"})
lens.record_error(error_type="ValueError", message="Bad input",
                  traceback="...")
lens.record_custom(event_name="custom.metric", data={"accuracy": 0.95})
```
</details>

---

## Plugin System

AgentLens has a production-grade plugin architecture for extending every layer: databases, exporters, and event processors.

### Architecture

```
  Events In ──► [Processors Pipeline] ──► [Database Plugin] ──► Storage
                       │                         │
                       │                    [Exporters]
                       │                    ├── S3
                       │                    ├── Kafka
                       │                    ├── Webhook
                       │                    └── File
                       │
                 [Event Hooks]
                 ├── on("llm.response", fn)
                 ├── on("error", fn)
                 └── on("session.end", fn)
```

### Database Plugins

Swap the storage backend without changing any application code.

```python
from agentlens.plugins import PluginRegistry
from agentlens.builtin_plugins import PostgreSQLPlugin, ClickHousePlugin

registry = PluginRegistry.get_instance()

# PostgreSQL — production OLTP
registry.register_database(
    PostgreSQLPlugin(dsn="postgresql://user:pass@localhost:5432/agentlens")
)

# ClickHouse — analytics at scale (millions of events/day)
registry.register_database(
    ClickHousePlugin(url="http://localhost:8123", database="agentlens")
)
```

| Plugin | Best For | Scale |
|---|---|---|
| **SQLite** (built-in) | Development, small deployments | < 100K events/day |
| **PostgreSQL** | Production OLTP workloads | < 10M events/day |
| **ClickHouse** | Analytics, massive scale | 100M+ events/day |

### Exporter Plugins

Send events to external systems for archival, streaming, or alerting.

```python
from agentlens.builtin_plugins import S3Exporter, WebhookExporter, FileExporter, KafkaExporter

registry = PluginRegistry.get_instance()

# Archive to S3 / MinIO
registry.register_exporter(S3Exporter(
    bucket="my-agentlens-data",
    prefix="events/",
    endpoint_url="http://localhost:9000"  # MinIO
))

# Forward errors to Slack
registry.register_exporter(WebhookExporter(
    url="https://hooks.slack.com/services/T.../B.../xxx",
    filter_types=["error", "session.end"]
))

# Stream to Kafka for downstream consumers
registry.register_exporter(KafkaExporter(
    bootstrap_servers="localhost:9092",
    topic="agentlens.events"
))

# Local JSONL files with rotation
registry.register_exporter(FileExporter(
    directory="./logs/agentlens",
    max_file_mb=100
))
```

### Event Processors

Transform, filter, or enrich events before storage.

```python
from agentlens.builtin_plugins import PIIRedactor, SamplingProcessor, FilterProcessor, EnrichmentProcessor

registry = PluginRegistry.get_instance()

# Redact PII (emails, phones, SSNs, API keys, credit cards)
registry.register_processor(PIIRedactor())

# Sample 10% of events (always keeps errors + session boundary events)
registry.register_processor(SamplingProcessor(rate=0.1))

# Drop noisy event types
registry.register_processor(FilterProcessor(drop_types=["custom.debug"]))

# Add environment metadata to every event
registry.register_processor(EnrichmentProcessor(
    metadata={"environment": "production", "region": "us-east-1", "version": "1.2.0"}
))
```

### Event Hooks

React to specific events in real-time.

```python
registry = PluginRegistry.get_instance()

# Sync hook
@registry.on("error")
def on_error(event):
    print(f"Error in {event['agent_name']}: {event.get('error_type')}")

# Async hook
@registry.on_async("session.end")
async def on_session_end(event):
    if event.get("total_cost_usd", 0) > 5.0:
        await send_alert(f"Expensive session: ${event['total_cost_usd']:.2f}")
```

### Custom Plugins

Implement the abstract base classes to build your own:

```python
from agentlens.plugins import DatabasePlugin, ExporterPlugin, EventProcessor

class MyDatabasePlugin(DatabasePlugin):
    async def init(self): ...
    async def insert_events(self, events): ...
    async def insert_session(self, session): ...
    async def get_sessions(self, limit, offset, agent, project): ...
    async def get_session_detail(self, session_id): ...
    async def get_events(self, limit, event_type, session_id): ...
    async def get_analytics(self, hours, project): ...
    async def cleanup(self, days): ...
    async def health_check(self): ...

class MyExporter(ExporterPlugin):
    async def export_events(self, events): ...

class MyProcessor(EventProcessor):
    def process(self, event) -> dict | None:  # Return None to drop
        ...
```

---

## MCP Support

AgentLens has first-class Model Context Protocol support in two ways:

### 1. MCP Client Monitoring

Track MCP tool calls and resource reads from your agent code:

```python
from agentlens.integrations.mcp import patch_mcp

patch_mcp(lens)

# Every call_tool, list_tools, and read_resource is captured
async with ClientSession(read, write) as session:
    tools = await session.list_tools()
    result = await session.call_tool("web_search", {"query": "AI agents"})
```

### 2. MCP Server — Query AgentLens from Claude Desktop

AgentLens ships as an MCP server that AI assistants can query directly.

**Add to Claude Desktop** (`claude_desktop_config.json`):

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

**Available MCP Resources:**
| Resource | Description |
|---|---|
| `agentlens://sessions` | Recent agent sessions |
| `agentlens://analytics` | Aggregated performance metrics |
| `agentlens://errors` | Recent errors and failures |
| `agentlens://health` | System health status |

**Available MCP Tools:**
| Tool | Description |
|---|---|
| `query_sessions` | Search sessions by agent name, status, time range |
| `query_analytics` | Get performance analytics with custom time windows |
| `query_errors` | Search errors by type and agent |
| `get_session_detail` | Get full timeline for a specific session |
| `create_alert_rule` | Create monitoring rules (error rate, cost threshold) |
| `get_system_health` | Check backend health and statistics |

**Example conversation with Claude:**
> "Show me all failed sessions from the research-agent in the last 24 hours"  
> "What's the average cost per session for my email-agent?"  
> "Create an alert if error rate exceeds 10% in any 5-minute window"

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            YOUR AGENT CODE                                  │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐     │
│  │  OpenAI  │  │ Anthropic│  │  Gemini  │  │LangChain │  │  Custom  │     │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘     │
│       └──────────────┴──────────────┴──────────────┴──────────────┘          │
│                                     │                                       │
│                          ┌──────────▼──────────┐                            │
│                          │   AgentLens SDK      │                           │
│                          │  • auto_patch()      │                           │
│                          │  • @monitor, @tool   │                           │
│                          │  • Event batching    │                           │
│                          │  • Circuit breaker   │                           │
│                          │  • DLQ + retry       │                           │
│                          └──────────┬───────────┘                           │
└─────────────────────────────────────┼───────────────────────────────────────┘
                                      │ HTTP POST /api/v1/events
                                      │ (batched, every 2s)
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        AGENTLENS BACKEND (FastAPI)                          │
│                                                                             │
│  ┌─────────────┐   ┌──────────────────┐   ┌─────────────────┐             │
│  │ Rate Limiter│──▶│ Event Pipeline   │──▶│ Database Plugin │             │
│  │ (100 req/s) │   │  ┌────────────┐  │   │  • SQLite       │             │
│  └─────────────┘   │  │ Processors │  │   │  • PostgreSQL   │             │
│                     │  │ • PII      │  │   │  • ClickHouse   │             │
│  ┌─────────────┐   │  │ • Filter   │  │   └─────────────────┘             │
│  │   Auth      │   │  │ • Sample   │  │                                    │
│  │ (API Key)   │   │  │ • Enrich   │  │   ┌─────────────────┐             │
│  └─────────────┘   │  └────────────┘  │──▶│    Exporters    │             │
│                     └──────────────────┘   │  • S3 / MinIO   │             │
│  ┌─────────────┐                           │  • Kafka        │             │
│  │  OTEL       │◀── OTLP JSON /v1/traces   │  • Webhook      │             │
│  │  Ingestion  │                           │  • File (JSONL) │             │
│  └─────────────┘                           └─────────────────┘             │
│                                                                             │
│  ┌─────────────┐   ┌──────────────────┐   ┌─────────────────┐             │
│  │  WebSocket  │◀── Live event feed   │   │  Cost Anomaly   │             │
│  │  /ws/live   │                      │   │  Detector       │             │
│  └─────────────┘   │  REST API        │   │  • 2× baseline  │             │
│                     │  • /sessions     │   │  • Auto-alert   │             │
│  ┌─────────────┐   │  • /events       │   └─────────────────┘             │
│  │   Alerts    │   │  • /analytics    │                                    │
│  │ (webhooks)  │   │  • /traces 🌳    │   ┌─────────────────┐             │
│  └─────────────┘   │  • /anomalies    │   │  Prompt Diff    │             │
│                     │  • /admin        │   │  • Similarity   │             │
│                     └──────────────────┘   │  • Line diff    │             │
│                                            └─────────────────┘             │
└─────────────────────────────┬───────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        DASHBOARD (React + Vite)                             │
│                                                                             │
│  ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌───────────┐              │
│  │ Overview  │  │ Sessions  │  │ Live Feed │  │ Anomalies │              │
│  │ • Stats   │  │ • List    │  │ • WS      │  │ • Trends  │              │
│  │ • Charts  │  │ • Detail  │  │ • Stream  │  │ • Alerts  │              │
│  │ • Top N   │  │ • Tree 🌳 │  │ • Filter  │  │ • Ack     │              │
│  └───────────┘  │ • Graph🔗 │  └───────────┘  └───────────┘              │
│                  │ • Diff   │                                              │
│  ┌───────────┐  └───────────┘  ┌───────────┐  ┌───────────┐              │
│  │  Alerts   │                  │   Admin   │  │   Setup   │              │
│  │ • Rules   │                  │ • Health  │  │ • Guide   │              │
│  │ • CRUD    │                  │ • Cleanup │  │ • Docs    │              │
│  │ • Webhook │                  │ • Demo 🎲 │  │           │              │
│  └───────────┘                  └───────────┘  └───────────┘              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Data Flow

1. **Instrumentation** — SDK patches LLM client libraries at import time. Every API call is intercepted, timed, and enriched with cost data.
2. **Batching** — Events are buffered in memory (max 10,000) and flushed every 2 seconds via HTTP POST to minimize overhead.
3. **Reliability** — Circuit breaker prevents cascading failures. Failed batches are saved to a Dead Letter Queue (JSON file) and retried on recovery.
4. **Pipeline** — Backend runs events through the processor pipeline (PII redaction → sampling → filtering → enrichment) before storage.
5. **Storage** — Pluggable database backend. Default SQLite with WAL mode. Upgrade to PostgreSQL or ClickHouse for scale.
6. **Export** — Events are simultaneously forwarded to configured exporters (S3, Kafka, webhooks).
7. **Presentation** — React dashboard polls REST API and subscribes to WebSocket for live updates.

### Event Types

| Event Type | Description | Auto-Captured By |
|---|---|---|
| `session.start` | Agent session begins | `@monitor` decorator |
| `session.end` | Agent session completes | `@monitor` decorator |
| `llm.request` | LLM API call made | `patch_openai`, `patch_anthropic`, etc. |
| `llm.response` | LLM response received | All LLM integrations |
| `tool.call` | Tool invoked | `@tool` decorator, MCP |
| `tool.result` | Tool returned result | `@tool` decorator, MCP |
| `tool.error` | Tool threw exception | `@tool` decorator |
| `agent.step` | Named agent step | `@step` decorator |
| `error` | Unhandled error | All decorators |
| `custom.*` | User-defined events | `lens.record_custom()` |

---

## API Reference

### REST Endpoints

| Method | Endpoint | Description | Role Required |
|---|---|---|---|
| `POST` | `/api/v1/events` | Ingest event batch from SDK | member |
| `GET` | `/api/v1/sessions` | List sessions (filter: `?agent=`, `?limit=`, `?offset=`) | viewer |
| `GET` | `/api/v1/sessions/{id}` | Session detail with full event timeline | viewer |
| `GET` | `/api/v1/events` | List events (filter: `?type=`, `?session_id=`, `?limit=`) | viewer |
| `GET` | `/api/v1/analytics` | Aggregated stats: sessions, cost, tokens, errors, top models/agents | viewer |
| `GET` | `/api/v1/live` | Last 60 seconds of events (poll-based live feed) | viewer |
| `POST` | `/api/v1/alerts` | Create alert rule | member |
| `GET` | `/api/v1/alerts` | List alert rules | viewer |
| `DELETE` | `/api/v1/alerts/{id}` | Delete alert rule | member |
| `POST` | `/api/v1/keys` | Create API key | admin |
| `GET` | `/api/v1/keys` | List API keys (no secrets) | admin |
| `DELETE` | `/api/v1/keys/{id}` | Revoke API key | admin |
| `POST` | `/api/v1/keys/{id}/rotate` | Rotate API key (grace period) | admin |
| `POST` | `/api/v1/keys/rotate-all` | Rotate all project keys | admin |
| `POST` | `/api/v1/projects` | Create project (auto-creates admin key) | admin |
| `GET` | `/api/v1/projects` | List projects | admin |
| `DELETE` | `/api/v1/projects/{id}` | Delete project + all data | admin |
| `GET` | `/api/v1/retention` | Get data retention policy | admin |
| `PUT` | `/api/v1/retention` | Set data retention policy | admin |
| `POST` | `/api/v1/retention/purge` | Manually trigger retention purge | admin |
| `GET` | `/api/v1/retention/history` | View purge history | admin |
| `GET` | `/api/v1/admin/encryption` | Encryption & security status | admin |
| `GET` | `/api/v1/audit` | View audit log | admin |
| `GET` | `/api/v1/admin/stats` | Admin statistics | admin |
| `POST` | `/api/v1/admin/cleanup` | Delete old data (`?days=30`) | admin |
| `POST` | `/v1/traces` | OpenTelemetry OTLP JSON ingestion | member |
| `GET` | `/api/v1/traces/{trace_id}` | Nested trace tree with waterfall timing | viewer |
| `GET` | `/api/v1/events/{id}/detail` | Event detail + similar prompts for diffing | viewer |
| `GET` | `/api/v1/events/{id}/diff/{other_id}` | Prompt/completion diff between two events | viewer |
| `GET` | `/api/v1/anomalies` | List detected cost anomalies | viewer |
| `GET` | `/api/v1/anomalies/trends` | Daily cost trends per agent | viewer |
| `POST` | `/api/v1/anomalies/{id}/acknowledge` | Acknowledge a cost anomaly | member |
| `POST` | `/api/v1/anomalies/detect` | Manually trigger anomaly detection | admin |
| `POST` | `/api/v1/demo/load` | Load ~500 demo events across 5 agent types | member |
| `GET` | `/api/v1/sessions/{id}/graph` | Agent execution graph (DAG) with nodes + edges | viewer |
| `GET` | `/api/health` | Health check with security posture (no auth) | — |
| `WS` | `/ws/live` | WebSocket live event stream | — |

Full OpenAPI docs: `http://localhost:8340/docs`

### SDK API

```python
from agentlens import AgentLens

lens = AgentLens(
    server_url="http://localhost:8340",  # Backend URL
    project_id="my-project",             # Project identifier
    api_key="your-api-key",              # optional auth
    flush_interval=2.0,                   # Batch flush interval (seconds)
    max_buffer_size=10000,                # Max events in memory
    sampling_rate=1.0,                    # 1.0 = keep all, 0.1 = 10%
    max_retries=3,                        # Retry attempts per batch
    circuit_breaker_threshold=5,          # Failures before circuit opens
    circuit_breaker_timeout=60,           # Seconds before half-open retry
)
```

---

## Security & Compliance

AgentLens is built for environments that handle sensitive data. Here's the security posture:

| Capability | Status | Details |
|---|---|---|
| **Encryption at rest** | ✅ | AES-128-CBC + HMAC-SHA256 (Fernet). Encrypts prompts, completions, tool args, errors |
| **Encryption in transit (TLS)** | ✅ | Built-in uvicorn SSL. Self-signed cert generator included. No nginx required |
| **RBAC** | ✅ | Admin / Member / Viewer roles with 14/7/4 permissions respectively |
| **API key rotation** | ✅ | Rotate with configurable grace period. Old key auto-expires |
| **PII redaction** | ✅ | Auto-scrubs emails, phones, SSNs, credit cards, API keys |
| **Audit logging** | ✅ | Every admin action logged with timestamp, IP, user-agent |
| **Data retention** | ✅ | Per-project policies, automated background purge, purge history |
| **Security headers** | ✅ | X-Frame-Options, CSP, HSTS, XSS-Protection, no-cache |
| **Multi-tenancy** | ✅ | Project-level data isolation with per-project API keys |
| **Self-hosted** | ✅ | Your data never leaves your infrastructure |
| **PCI-DSS** | ⚠️ | Foundation in place (encryption, RBAC, audit). Formal certification requires audit |
| **SOC2** | ⚠️ | Controls implemented. Formal compliance requires third-party audit |

### Enable Encryption

```bash
# Auto-generates key on first start (saved to .encryption_key)
python -c "import uvicorn; uvicorn.run('main:app', host='0.0.0.0', port=8340)"

# Or set your own key
export AGENTLENS_ENCRYPTION_KEY="your-base64-fernet-key"
```

### Enable TLS

```bash
# Generate self-signed cert (for development)
cd backend
python tls.py --generate-self-signed

# Set cert paths and start
export AGENTLENS_TLS_CERT=agentlens-cert.pem
export AGENTLENS_TLS_KEY=agentlens-key.pem
python tls.py --start
# Server starts on https://localhost:8340
```

### Key Rotation

```bash
# Rotate a specific key (24h grace period — old key keeps working)
curl -X POST http://localhost:8340/api/v1/keys/{key_id}/rotate \
  -H "Authorization: Bearer al_admin_key" \
  -H "Content-Type: application/json" \
  -d '{"grace_period_hours": 24}'

# Rotate ALL keys
curl -X POST http://localhost:8340/api/v1/keys/rotate-all \
  -H "Authorization: Bearer al_admin_key" \
  -d '{"grace_period_hours": 48}'
```

### Data Retention

```bash
# Set 90-day retention
curl -X PUT http://localhost:8340/api/v1/retention \
  -H "Authorization: Bearer al_admin_key" \
  -H "Content-Type: application/json" \
  -d '{"retention_days": 90, "delete_events": true, "delete_sessions": true}'

# Auto-purge runs in background every hour. Manual purge:
curl -X POST http://localhost:8340/api/v1/retention/purge \
  -H "Authorization: Bearer al_admin_key"
```

---

## Multi-Language Quick Start

### TypeScript (Full Type Safety)

```typescript
import { AgentLens, patchOpenAI } from '@agentlens/sdk';
import OpenAI from 'openai';

const lens = new AgentLens({
  serverUrl: 'http://localhost:8340',
  agentName: 'my-agent',
  sampleRate: 1.0,
});

// Auto-patch OpenAI — all calls tracked with zero code changes
const openai = new OpenAI();
patchOpenAI(openai, lens);

lens.startSession('my-agent');

// This call is automatically tracked: model, tokens, cost, latency
const response = await openai.chat.completions.create({
  model: 'gpt-4o',
  messages: [{ role: 'user', content: 'Hello!' }],
});

lens.endSession(true);
await lens.shutdown();
```

Also supports `patchAnthropic()` for Claude. Full types for all events, configs, and API responses.

Install: `npm install @agentlens/sdk`

### JavaScript (Vanilla)

```javascript
import { AgentLens } from './agentlens.js';

const lens = new AgentLens('http://localhost:8340', 'al_your_key');
const session = lens.startSession('my-agent');

lens.trackLLMCall({
    model: 'gpt-4o', prompt: 'Hello', completion: 'Hi!',
    inputTokens: 5, outputTokens: 3, latencyMs: 200
});

lens.endSession(session, true);
await lens.shutdown();
```

### Go

```go
lens := agentlens.New("http://localhost:8340", "al_your_key")
defer lens.Shutdown()

sess := lens.StartSession("my-agent")
lens.TrackLLMCall(agentlens.LLMEvent{Model: "gpt-4o", Prompt: "Hello", LatencyMs: 200})
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

### Any Language (cURL)

```bash
curl -X POST http://localhost:8340/api/v1/events \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer al_your_key" \
  -d '{"events": [{"event_type": "llm.response", "model": "gpt-4o", "prompt": "Hello", "completion": "Hi!"}]}'
```

---

## Deployment

### Docker Compose (recommended)

```yaml
version: '3.8'
services:
  backend:
    build: ./backend
    ports:
      - "8340:8340"
    environment:
      - AGENTLENS_API_KEY=your-secret-key
    volumes:
      - agentlens-data:/app/data

  dashboard:
    build: ./dashboard
    ports:
      - "5173:80"
    depends_on:
      - backend

volumes:
  agentlens-data:
```

### Production with PostgreSQL

```yaml
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_DB: agentlens
      POSTGRES_USER: agentlens
      POSTGRES_PASSWORD: secret
    volumes:
      - pg-data:/var/lib/postgresql/data

  backend:
    build: ./backend
    environment:
      - DATABASE_URL=postgresql://agentlens:secret@postgres:5432/agentlens
      - AGENTLENS_API_KEY=your-secret-key
    depends_on:
      - postgres
```

### Production with ClickHouse (high scale)

```yaml
services:
  clickhouse:
    image: clickhouse/clickhouse-server:latest
    ports:
      - "8123:8123"
    volumes:
      - ch-data:/var/lib/clickhouse
```

---

## Configuration

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `AGENTLENS_SERVER_URL` | `http://localhost:8340` | Backend server URL |
| `AGENTLENS_API_KEY` | _(none)_ | API key for authenticated requests |
| `AGENTLENS_PROJECT_ID` | `default` | Default project identifier |
| `AGENTLENS_FLUSH_INTERVAL` | `2.0` | Event batch flush interval (seconds) |
| `AGENTLENS_SAMPLING_RATE` | `1.0` | Event sampling rate (0.0–1.0) |
| `AGENTLENS_LOG_LEVEL` | `WARNING` | SDK log verbosity |

---

## Tech Stack

| Component | Technology | Why |
|---|---|---|
| **SDK** | Python, zero dependencies | Works everywhere — no dependency conflicts |
| **Backend** | FastAPI + async SQLite | Fast, modern, battle-tested |
| **Dashboard** | React 18 + Vite | Instant HMR, lightweight |
| **Database** | SQLite → PostgreSQL → ClickHouse | Scale from laptop to cloud |
| **Protocol** | REST + WebSocket | Standard, no vendor lock-in |
| **Deploy** | Docker Compose | One command to production |

---

## Comparison

| Feature | AgentLens | Langfuse | LangSmith | Helicone |
|---|---|---|---|---|
| Agent behavior tracking | **Yes** | Partial | Partial | No |
| Tool call monitoring | **Yes** | Yes | Yes | No |
| Multi-framework support | **8+** | 5+ | LangChain focus | Proxy-based |
| OpenTelemetry ingestion | **Yes** | **Yes** | No | No |
| Nested trace tree/waterfall | **Yes** | **Yes** | **Yes** | No |
| Prompt replay & diff | **Yes** | Partial | **Yes** | No |
| Cost anomaly detection | **Yes (auto)** | No | No | No |
| Agent graph (DAG) | **Yes** | No | Partial | No |
| CLI verification tool | **Yes** | No | No | No |
| MCP integration | **Yes** | No | No | No |
| Plugin system (DB/export) | **Yes** | No | No | No |
| Self-hosted option | **Yes** | **Yes** | No | Partial |
| Zero SDK dependencies | **Yes** | No | No | N/A |
| TypeScript SDK (typed) | **Yes** | **Yes** | **Yes** | N/A |
| PII redaction (built-in) | **Yes** | No | No | No |
| Encryption at rest | **Yes** | No | No | No |
| Cost tracking | Auto | Auto | Auto | Auto |
| RBAC / API key scoping | **Yes** | Yes | Yes | Yes |
| Prompt management/versioning | No | **Yes** | **Yes** | No |
| LLM-as-a-judge evals | No | **Yes** | **Yes** | No |
| Datasets / experiments | No | **Yes** | **Yes** | No |
| Prometheus `/metrics` | **Yes** | No | No | No |
| Open source | **MIT** | **MIT** | No | Partial |
| Maturity | Early | Established | Established | Established |

### Where AgentLens matches or beats Langfuse

**Parity:** OTEL ingestion, nested traces, self-hosting, multi-language SDKs (Python/TS/JS/Go/Java), cost tracking, RBAC.

**Beats outright:** Zero-dependency SDK, zero-config cost anomaly detection (Langfuse doesn't have it), PII redaction built-in, plugin architecture (swap DB/exporters), MCP-native server + client, agent graph (DAG), encryption at rest, CLI verification, prompt diff, one-click demo data.

### Where Langfuse still leads

**Maturity & community** — larger user base, more battle-tested in production at scale.

**Prompt management** — versioned prompt templates with A/B testing. AgentLens tracks prompts but doesn't manage them.

**LLM-as-a-judge evals** — built-in evaluation framework using LLMs to score outputs.

**Datasets & experiments** — structured experiment tracking for prompt optimization.

**Ecosystem partnerships** — direct integrations with Pydantic AI, smolagents, Strands, AWS Bedrock AgentCore.

### Honest assessment

Langfuse is the closest open-source competitor and is more mature with a larger ecosystem. AgentLens is a genuinely competitive alternative that differentiates on **developer experience** (zero deps, CLI verify, one-click demo), **security** (encryption at rest, PII redaction, TLS built-in), and **unique features** (cost anomaly auto-detection, plugin architecture, MCP-native, agent graph). If you need a battle-tested solution today with a large community, consider Langfuse. If you want a lightweight, pluggable, framework-agnostic tool you can self-host with zero vendor lock-in — and features Langfuse doesn't have — AgentLens is built for that.

---

## Roadmap

AgentLens is feature-competitive. All stickiness/community features are now shipped.

| Priority | Feature | Status | Notes |
|---|---|---|---|
| ✅ Done | **User/session grouping** — `lens.set_user("user_123")`, filter by user in dashboard | Shipped | SDK `set_user()`, DB `user_id` column, dashboard filter |
| ✅ Done | **Prometheus `/metrics` endpoint** — `agentlens_events_total`, `agentlens_cost_usd_total`, `agentlens_llm_latency_seconds` | Shipped | `GET /metrics` — native, no dependencies |
| ✅ Done | **Helm chart for Kubernetes** — deployment, service, ingress, PVC, secrets, ServiceMonitor | Shipped | `helm/agentlens/` — ready to install |
| ✅ Done | **`agentlens demo` CLI command** — loads 500 events from 5 agent types | Shipped | `agentlens demo [url]` |
| ✅ Done | **Grafana dashboard template** — 14 panels: cost, latency p50/95/99, errors, events by type | Shipped | `grafana/agentlens-dashboard.json` — import into Grafana |
| ✅ Done | **Langfuse migration guide** — side-by-side SDK swap, full API mapping | Shipped | `docs/migrating-from-langfuse.md` |
| 🔴 Won't | Prompt management/versioning | — | Not our lane. Use Langfuse or PromptLayer for this |
| 🔴 Won't | LLM-as-a-judge evals | — | Evals are a different product. Use Braintrust, Langfuse, or custom |
| 🔴 Won't | Playground / chat UI | — | Observability, not interaction. Stay focused |

### Coming from Langfuse?

Switching is a one-line SDK change:

```python
# Before (Langfuse)
from langfuse.decorators import observe

@observe()
def my_agent(query):
    ...

# After (AgentLens)
from agentlens import monitor

@monitor("my-agent")
def my_agent(query):
    ...
```

AgentLens auto-patches OpenAI, Anthropic, Gemini, LangChain, CrewAI, and LiteLLM — just call `auto_patch()` and your existing code works with zero changes. See [`docs/migrating-from-langfuse.md`](docs/migrating-from-langfuse.md) for a full API mapping and step-by-step guide.

---

### User Tracking

```python
lens = AgentLens(server_url="http://localhost:8340")

# Set user — all subsequent events are tagged
lens.set_user("user_123")
session = lens.start_session(agent_name="chatbot")
# ... agent code ...
lens.end_session()

# Or set per-session
session = lens.start_session(agent_name="chatbot", user_id="user_456")

# Global metadata
lens.set_metadata(environment="prod", version="1.2")
```

Filter by user in the dashboard or API:
```
GET /api/v1/sessions?user=user_123
```

### Prometheus Metrics

```
GET /metrics
```

Exposes counters (`agentlens_events_total`, `agentlens_cost_usd_total`, `agentlens_errors_total`, `agentlens_tokens_total`), histograms (`agentlens_llm_latency_seconds`, `agentlens_llm_cost_usd`), and gauges (`agentlens_uptime_seconds`). No dependencies — pure stdlib implementation.

### Grafana Dashboard

Import [`grafana/agentlens-dashboard.json`](grafana/agentlens-dashboard.json) into Grafana. 14 panels: cost trends, error rates, latency p50/p95/p99, events by type, token consumption, and more.

### Kubernetes (Helm)

```bash
helm install agentlens ./helm/agentlens \
  --set image.tag=0.3.0 \
  --set persistence.enabled=true \
  --set prometheus.serviceMonitor.enabled=true
```

See [`helm/agentlens/values.yaml`](helm/agentlens/values.yaml) for all configurable values.

---

## Project Structure

```
agentlens/
├── sdk/
│   ├── python/agentlens/              # Python SDK (full-featured)
│   │   ├── __init__.py                # Package entry — v0.3.0
│   │   ├── client.py                  # Core client — batching, circuit breaker, DLQ
│   │   ├── cli.py                     # CLI — `agentlens verify` command
│   │   ├── decorators.py              # @monitor, @tool, @step
│   │   ├── events.py                  # Event/Session models, EventType enum, cost tables
│   │   ├── plugins.py                 # Plugin ABCs — DatabasePlugin, ExporterPlugin, EventProcessor
│   │   ├── builtin_plugins.py         # Built-in: PostgreSQL, ClickHouse, S3, Kafka, Webhook, PII, etc.
│   │   └── integrations/
│   │       ├── openai.py              # OpenAI auto-patch
│   │       ├── anthropic.py           # Anthropic/Claude auto-patch
│   │       ├── google_adk.py          # Gemini + Google ADK auto-patch
│   │       ├── langchain.py           # LangChain callback handler
│   │       ├── crewai.py              # CrewAI auto-patch
│   │       ├── litellm.py             # LiteLLM auto-patch (100+ providers)
│   │       ├── mcp.py                 # MCP client interceptor + MCP server
│   │       └── auto.py                # Auto-detect and patch all frameworks
│   ├── typescript/                    # TypeScript SDK (full types)
│   │   ├── src/client.ts              # Core client — batching, circuit breaker, wrappers
│   │   ├── src/types.ts               # Full type definitions for all events + API
│   │   ├── src/patches/openai.ts      # OpenAI auto-patch
│   │   ├── src/patches/anthropic.ts   # Anthropic auto-patch
│   │   ├── package.json               # @agentlens/sdk
│   │   └── tsconfig.json
│   ├── javascript/                    # JavaScript SDK (vanilla)
│   │   ├── agentlens.js               # Full SDK with OpenAI wrapper
│   │   ├── example.js                 # Quick start example
│   │   └── package.json
│   ├── go/                            # Go SDK
│   │   ├── agentlens.go               # Full SDK
│   │   └── example/main.go            # Go example
│   ├── java/src/io/agentlens/         # Java SDK (Java 11+, zero deps)
│   │   └── AgentLens.java
│   └── rest-api/                      # Universal REST examples
│       └── examples.sh                # cURL examples for all endpoints
├── backend/
│   ├── main.py                        # FastAPI server — REST + WebSocket + RBAC + OTEL + alerts
│   ├── database.py                    # Async SQLite with connection pool (WAL mode)
│   ├── auth.py                        # RBAC, API key management, key rotation, audit, multi-tenancy
│   ├── otel.py                        # OpenTelemetry OTLP JSON ingestion — span→event mapping
│   ├── anomaly.py                     # Cost anomaly detection + prompt similarity/diff
│   ├── demo_data.py                   # Demo data generator — 500 events, 5 agent types
│   ├── encryption.py                  # Field-level encryption at rest (AES-128-CBC + HMAC-SHA256)
│   ├── retention.py                   # Data retention policies, automated purge, purge history
│   ├── tls.py                         # Built-in TLS/HTTPS support, self-signed cert generator
│   ├── requirements.txt
│   └── Dockerfile
├── dashboard/
│   ├── src/App.jsx                    # React dashboard — 8 pages, trace tree, graph, anomalies
│   ├── src/api.js                     # API client (OTEL, anomalies, traces, diff, demo)
│   ├── src/main.jsx                   # Entry point
│   ├── package.json                   # Vite 5 + React 18
│   └── vite.config.js                 # Proxy to backend
├── tests/
│   ├── sdk/test_sdk.py                # 40 SDK unit tests
│   └── backend/test_api.py            # 50 backend integration tests (RBAC, OTEL, traces, anomalies, graph)
├── examples/
│   └── demo_agent.py                  # Demo with 4 agent types
├── .github/workflows/ci.yml           # CI: SDK tests (Python 3.9-3.13), backend tests, dashboard build, lint
├── docker-compose.yml
└── README.md
```

---

## Examples

### Basic Agent

```python
from agentlens import AgentLens, monitor, auto_patch

lens = AgentLens(server_url="http://localhost:8340")
auto_patch()

@monitor("my-agent")
def run(task):
    response = openai.chat.completions.create(
        model="gpt-4o", messages=[{"role": "user", "content": task}]
    )
    return response.choices[0].message.content

run("Summarize the latest AI news")
```

### Multi-Agent System

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

### Production Setup with Plugins

```python
from agentlens import AgentLens, auto_patch, PluginRegistry
from agentlens.builtin_plugins import (
    PostgreSQLPlugin, S3Exporter, WebhookExporter,
    PIIRedactor, SamplingProcessor, EnrichmentProcessor
)

# Initialize
lens = AgentLens(server_url="http://localhost:8340")
auto_patch()

# Configure plugins
registry = PluginRegistry.get_instance()

# Storage
registry.register_database(PostgreSQLPlugin(dsn="postgresql://..."))

# Export errors to Slack
registry.register_exporter(WebhookExporter(
    url="https://hooks.slack.com/services/...",
    filter_types=["error"]
))

# Archive to S3
registry.register_exporter(S3Exporter(bucket="agent-data"))

# Security
registry.register_processor(PIIRedactor())

# Reduce volume in production
registry.register_processor(SamplingProcessor(rate=0.1))

# Tag environment
registry.register_processor(EnrichmentProcessor(
    metadata={"env": "production", "version": "2.1.0"}
))
```

---

## Pricing (Hosted — Coming Soon)

| Plan | Price | Events/month | Projects |
|---|---|---|---|
| **Free** | $0 | 10,000 | 1 |
| **Pro** | $49/mo | 500,000 | 10 |
| **Team** | $149/mo | 5,000,000 | Unlimited |
| **Enterprise** | Custom | Unlimited | Unlimited |

**Self-hosted is free forever. No limits. No telemetry.**

---

## Contributing

```bash
# Clone
git clone https://github.com/agentlens/agentlens.git
cd agentlens

# Backend
cd backend && pip install -r requirements.txt
uvicorn main:app --reload --port 8340

# Dashboard
cd dashboard && npm install && npm run dev

# SDK (editable install)
cd sdk/python && pip install -e ".[dev]"

# Run tests
pytest
```

---

## License

MIT — use it however you want, commercially or otherwise.

---

**Built for developers who ship AI agents and need to know what they're doing.**

---

## Launch Checklist

- [ ] Screenshots / GIF in README
- [ ] `pip install agentlens` working on PyPI
- [ ] `npm install @agentlens/sdk` working on npm
- [ ] `docker compose up` verified on clean machine
- [ ] Publish Helm chart to ArtifactHub
- [x] Prometheus `/metrics` endpoint
- [x] Grafana dashboard template
- [x] `agentlens demo` CLI command
- [x] Migration guide from Langfuse
- [x] User/session grouping (`set_user()`)
- [x] Helm chart for Kubernetes
- [x] 100 tests passing
