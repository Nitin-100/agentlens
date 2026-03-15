# AgentLens — Quick Start Guide

<p align="center">
  <video src="Demo.mp4" width="100%" autoplay loop muted playsinline>
    Your browser does not support the video tag. <a href="Demo.mp4">Watch the demo</a>.
  </video>
</p>

Pick your path:

| # | You are... | Time | Jump to |
|---|-----------|------|---------|
| 1 | **Already running agents** in production — want observability without redeploying | 2 min | [Path 1](#path-1--already-running-agents-add-observability-without-redeploying) |
| 2 | **Building new agents** — want to instrument from the start | 5 min | [Path 2](#path-2--building-new-agents-instrument-from-scratch) |
| 3 | **Evaluating AgentLens** — just want to see the product with demo data | 1 min | [Path 3](#path-3--just-testing-run-the-full-product-with-demo-data) |

---

## Prerequisites (all paths)

- Python 3.9+
- Node.js 18+ (for dashboard)

---

## Start AgentLens (required for all paths)

You need **3 terminals** — one for backend, one for dashboard, one for SDK/commands.

### Terminal 1: Backend

```bash
cd backend
pip install -r requirements.txt
```

Clean old data (optional, for a fresh start):
```bash
# Windows
Remove-Item agentlens.db, agentlens.db-shm, agentlens.db-wal, .encryption_key -ErrorAction SilentlyContinue

# Linux/Mac
rm -f agentlens.db agentlens.db-shm agentlens.db-wal .encryption_key
```

Start the server:
```bash
cd backend
python -c "import uvicorn; uvicorn.run('main:app', host='0.0.0.0', port=8340)"
```

> **Port already in use?** Kill the old process first:
> ```powershell
> # Windows
> $p = Get-NetTCPConnection -LocalPort 8340 -EA SilentlyContinue | Select -Expand OwningProcess -Unique
> if ($p) { Stop-Process -Id $p -Force }
> ```
> ```bash
> # Linux/Mac
> kill $(lsof -t -i :8340) 2>/dev/null
> ```

Verify: `curl http://localhost:8340/api/health` → `{"status":"ok"}`

### Terminal 2: Dashboard

```bash
cd dashboard
npm install
npx vite --host
```

Open the URL shown in terminal output (usually `http://localhost:5173` or `http://localhost:5174`).

### Terminal 3: Install the SDK

```bash
cd sdk/python
pip install -e .
```

Now load demo data:
```bash
agentlens demo
```

Or via API:
```bash
curl -X POST http://localhost:8340/api/v1/demo/load
```

Refresh the dashboard — you'll see sessions, traces, costs, and anomalies.

---

# Path 1 — Already Running Agents (Add Observability Without Redeploying)

> You have agents running in production. You don't want to rewrite your code or redeploy.
> AgentLens can auto-patch your LLM calls at import time — **zero changes to your existing agent code**.

### How it works

AgentLens uses **monkey-patching** — it wraps the LLM client libraries (OpenAI, Anthropic, etc.) at runtime. Your existing function calls, API keys, and response handling stay exactly the same. AgentLens just observes them.

### Step 1: Add a startup file

Create a file called `agentlens_init.py` next to your existing agent code:

```python
# agentlens_init.py — Add this file. Don't touch your agent code.
from agentlens import AgentLens, auto_patch

lens = AgentLens(
    server_url="http://localhost:8340",   # your AgentLens server
    api_key="al_default_key",             # default key, change for production
    project="my-project",
    sample_rate=1.0,                      # 1.0 = capture everything, use 0.1 for 10% in prod
)
auto_patch()

# That's it. Every OpenAI/Anthropic/Gemini/LiteLLM/CrewAI call
# in this process is now automatically captured.
```

### Step 2: Import it before your agent runs

Add **one line** to your existing entry point:

```python
# your_existing_main.py

import agentlens_init    # <-- add this ONE line at the top

# ... rest of your code stays 100% the same
from my_agent import run_agent
run_agent()
```

**That's it.** No decorators. No code changes. No redeployment of agent logic.

### What gets captured automatically

| Framework | What's tracked |
|-----------|---------------|
| **OpenAI** | model, prompt, completion, tokens, cost, latency |
| **Anthropic** | model, messages, response, tokens, cost, latency |
| **Google Gemini** | model, prompt, response, tokens |
| **Google ADK** | agent steps, tool calls |
| **LiteLLM** | all 100+ providers routed through LiteLLM |
| **CrewAI** | agent execution, task results, crew kickoff |
| **LangChain** | chain runs, LLM calls, tool calls (via callback handler) |

### LangChain special case

LangChain uses callbacks instead of monkey-patching. Add the handler to your chain:

```python
# For LangChain — add callback handler (only extra step needed)
from agentlens.integrations.langchain import AgentLensCallbackHandler

handler = AgentLensCallbackHandler()

# Pass to your existing chain/agent
result = my_chain.invoke({"input": "..."}, config={"callbacks": [handler]})
# Or: agent.run("...", callbacks=[handler])
```

### Production tips

```python
lens = AgentLens(
    server_url="https://agentlens.internal:8340",
    api_key="al_prod_key_xxxxx",
    sample_rate=0.1,          # only capture 10% of sessions in prod
    max_retries=3,            # retry failed flushes
    dlq_path="./dlq.jsonl",   # save failed events to disk, auto-replay later
)
```

| Feature | What it does |
|---------|-------------|
| **Circuit Breaker** | Stops sending after 5 consecutive failures, auto-recovers in 30s |
| **Dead Letter Queue** | Failed events saved to disk, replayed when connection recovers |
| **Graceful Shutdown** | All buffered events drained on process exit (SIGTERM/SIGINT) |
| **Sampling** | `sample_rate=0.1` captures only 10% of sessions |
| **PII Redaction** | Built-in — strips emails, phone numbers, SSNs from event data |

### Verify it works

```bash
agentlens verify http://localhost:8340
```

You should see:
```
AgentLens Server Verification
  Server Reachable       HTTP 200
  Health Endpoint        status=ok, v=0.3.0
  Events Writable        inserted=1
  Sessions Readable      HTTP 200
  Analytics Working      HTTP 200
  All checks passed!
```

Open the dashboard → **Sessions** page. You'll see your agent's sessions appearing in real-time.

---

# Path 2 — Building New Agents (Instrument from Scratch)

> You're writing a new agent and want full observability from day one.
> Use decorators for explicit control over what gets tracked.

### Step 1: Initialize AgentLens

```python
from agentlens import AgentLens, monitor, tool, step, auto_patch

lens = AgentLens(
    server_url="http://localhost:8340",
    api_key="al_default_key",
    project="my-project",
)

# Option A: Auto-patch all LLM libraries (easiest)
auto_patch()

# Option B: Use decorators for fine-grained control (below)
```

### Step 2: Decorate your agent

```python
from agentlens import monitor, tool, step

@monitor("research-agent")
def research_agent(query: str):
    """This decorator auto-creates a session, tracks success/failure, and records timing."""

    # Step 1: Search
    results = search_web(query)

    # Step 2: Analyze
    summary = analyze(results)

    # Step 3: LLM call (auto-captured if you used auto_patch)
    import openai
    response = openai.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": f"Summarize: {summary}"}]
    )

    return response.choices[0].message.content


@tool("web-search")
def search_web(query: str):
    """Tracked as a tool call — name, input, output, duration all captured."""
    import requests
    return requests.get(f"https://api.example.com/search?q={query}").json()


@step("analyze")
def analyze(results: list):
    """Tracked as a processing step within the session."""
    return [r["title"] for r in results[:5]]
```

### What each decorator does

| Decorator | Purpose | What it captures |
|-----------|---------|-----------------|
| `@monitor("agent-name")` | Wraps your top-level agent function | Creates a session, records start/end time, success/failure, input/output |
| `@tool("tool-name")` | Wraps a tool/function call | Tool name, input args, output result, duration, errors |
| `@step("step-name")` | Wraps a processing step | Step name, duration, errors — shows as a node in the trace tree |

### Step 3: Manual LLM tracking (if not using auto_patch)

If you're calling an LLM directly without auto_patch, record it explicitly:

```python
import time, openai

start = time.time()
response = openai.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Hello"}]
)
latency = (time.time() - start) * 1000

# Record manually
lens.llm_call(
    model="gpt-4o",
    prompt="Hello",
    completion=response.choices[0].message.content,
    input_tokens=response.usage.prompt_tokens,
    output_tokens=response.usage.completion_tokens,
    cost_usd=0.002,        # calculate based on your pricing
    latency_ms=latency,
)
```

### Step 4: Track users and sessions

```python
# Tag events with a user ID
lens.set_user("user_123")

# Manual session management (alternative to @monitor)
session = lens.start_session(agent_name="booking-agent", input_data={"task": "book flight"})

# ... your agent logic ...

lens.end_session(session_id=session.session_id, success=True, output_data="Flight booked")
```

### Step 5: Record errors

```python
try:
    result = risky_operation()
except Exception as e:
    lens.record_error(e, context="Failed during data processing")
    raise
```

### Step 6: Custom events

```python
# Track anything that doesn't fit the built-in types
lens.custom_event("cache.hit", data={"key": "user_prefs", "age_ms": 42})
lens.custom_event("guardrail.triggered", data={"rule": "toxicity", "score": 0.87})
```

### Async support

All decorators work with async functions automatically:

```python
@monitor("async-agent")
async def my_async_agent(query: str):
    results = await search_async(query)
    return results

@tool("async-search")
async def search_async(query: str):
    async with aiohttp.ClientSession() as session:
        async with session.get(f"https://api.example.com/search?q={query}") as resp:
            return await resp.json()
```

### Full example

```python
from agentlens import AgentLens, monitor, tool, step, auto_patch

# 1. Initialize
lens = AgentLens(server_url="http://localhost:8340", api_key="al_default_key")
auto_patch()

# 2. Define tools
@tool("search")
def search_db(query):
    return [{"id": 1, "title": "Result 1"}, {"id": 2, "title": "Result 2"}]

@tool("fetch")
def fetch_page(url):
    import requests
    return requests.get(url).text[:500]

# 3. Define steps
@step("rank")
def rank_results(results):
    return sorted(results, key=lambda r: r["id"], reverse=True)

# 4. Define agent
@monitor("research-agent")
def research(query):
    results = search_db(query)
    ranked = rank_results(results)
    # OpenAI call auto-captured by auto_patch
    import openai
    resp = openai.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": f"Summarize: {ranked}"}]
    )
    return resp.choices[0].message.content

# 5. Run
lens.set_user("nitin")
answer = research("AI observability tools 2026")
lens.flush()
print(answer)
```

---

# Path 3 — Just Testing (Run the Full Product with Demo Data)

> You want to see what AgentLens looks like with real-ish data before committing to anything.
> One command loads ~500 events across 5 agent types.

### Step 1: Load demo data

After starting the backend and dashboard (see [Start AgentLens](#start-agentlens-required-for-all-paths)):

```bash
agentlens demo
```

Or if `agentlens` isn't on your PATH:
```bash
python -c "from agentlens.cli import main; import sys; sys.argv = ['agentlens', 'demo']; main()"
```

You'll see:
```
Loading AgentLens demo data...
Inserted ~500 events across 5 agents
Demo data loaded! Open the dashboard to explore.
```

### Step 2: Explore every page

Refresh the dashboard at `http://localhost:5173`. Here's a walkthrough of every page:

#### Overview Page
The landing page shows your fleet at a glance:
- **Total Events** — ~500 events across all agents
- **Total Cost** — accumulated LLM spend with trend graphs
- **Error Rate** — percentage of failed sessions
- **Top Agents** — which agents are most active
- **Recent Sessions** — latest agent runs with status (success/failed)

#### Sessions Page
Click **Sessions** in the sidebar:
- See all 5 demo agent types: `booking-agent`, `research-agent`, `support-agent`, `code-agent`, `data-pipeline`
- Filter by agent name or user
- Click any session to drill into details

#### Session Detail (click any session)
Each session has 7 tabs:

| Tab | What to look for |
|-----|-----------------|
| **Trace Tree** | Nested hierarchy: session.start -> agent steps -> LLM calls / tool calls. Expand nodes. Waterfall bars show timing. |
| **Graph** | DAG visualization: session.start -> step1 -> step2 -> session.end, with LLM/tool leaves below each step |
| **Timeline** | Chronological flat list of every event in the session |
| **LLM Calls** | Model name, token counts, cost, latency for each LLM call |
| **Tools** | Tool name, duration, result for each tool invocation |
| **Errors** | Error type, message, stack trace (if the session had errors) |
| **Raw** | Full JSON of every event — useful for debugging |

#### Live Feed
Click **Live Feed** in the sidebar:
- Shows real-time streaming events via WebSocket
- Load demo data again to see events appear live

#### Anomalies
Click **Anomalies** in the sidebar:
- Cost spike detection across your agents
- Click **Run Detection** to scan for anomalies in the demo data
- View trends chart showing cost over time

#### Alerts
Click **Alerts** in the sidebar:
- Create alert rules with 4 condition types:

| Condition | Example |
|-----------|---------|
| **Cost Threshold $** | Alert when spend exceeds $10 in 5 minutes |
| **Error Rate %** | Alert when failure rate exceeds 20% |
| **Latency Avg (ms)** | Alert when avg latency exceeds 5000ms |
| **Failure Streak** | Alert after 5 consecutive failed sessions |

- Enter a Slack/Discord/PagerDuty webhook URL to get notified
- Try creating one: Name: "High cost alert", Condition: Cost, Threshold: 10, Webhook: your Slack URL

#### Admin
Click **Admin** in the sidebar:
- **DB Size** — current database size in MB
- **Total Events** — count of all stored events
- **Total Sessions** — count of all sessions
- **Status** — green "Healthy" when all systems nominal
- **Data Retention** — delete events older than N days
- **Load Demo Data** — reload demo data anytime from this page

### Step 3: Try the CLI tools

```bash
# Verify the server is working end-to-end
agentlens verify http://localhost:8340

# Load more demo data
agentlens demo

# Check server health
curl http://localhost:8340/api/health
```

### Demo data details

The demo generates 5 different agent types with realistic patterns:

| Agent | What it simulates |
|-------|------------------|
| `booking-agent` | Flight/hotel booking with search tools, payment processing |
| `research-agent` | Web research with search, scraping, summarization |
| `support-agent` | Customer support with KB lookup, ticket creation |
| `code-agent` | Code generation with linting, testing, deployment |
| `data-pipeline` | ETL pipeline with extraction, transformation, loading |

Each session includes:
- **session.start** -> **agent.step** (2-4 steps) -> **session.end**
- LLM calls with realistic token counts and costs
- Tool calls with duration and results
- Some sessions include errors and retries
- Cost varies to trigger anomaly detection

---

## Default Credentials

| Key | Value |
|-----|-------|
| API Key | `al_default_key` |
| Project | `default` |

The default key is created on first startup. For production, create new keys via the API.

---

## Docker (Alternative Setup)

If you prefer Docker over manual setup:

```bash
docker compose up -d
```

This starts both backend (port 8340) and dashboard (port 5173).

Then load demo data:
```bash
pip install -e sdk/python
agentlens demo --server http://localhost:8340
```

---

## Troubleshooting

**Port 8340 already in use:**
```powershell
# Windows
Get-NetTCPConnection -LocalPort 8340 | Select-Object OwningProcess
Stop-Process -Id <PID> -Force
```
```bash
# Linux/Mac
lsof -i :8340 && kill $(lsof -t -i :8340)
```

**Dashboard shows "Server: unreachable":**
- Backend must be running on port 8340
- CORS is allowed by default — no config needed

**`agentlens` command not found:**
```bash
pip install -e sdk/python
# Or run directly: python -m agentlens demo
```

**Events not appearing in dashboard:**
- Check API key matches (`al_default_key` by default)
- Call `lens.flush()` to force-send buffered events
- Check backend terminal for error logs

**Auto-patch not capturing calls:**
- `import agentlens_init` must come **before** importing the LLM library
- `auto_patch()` returns a dict showing what was patched — check the output

---

## Project Structure

```
agentlens/
├── backend/           # FastAPI server (Python)
│   ├── main.py        # API endpoints
│   ├── database.py    # SQLite storage
│   ├── auth.py        # RBAC & API keys
│   └── demo_data.py   # Demo data generator
├── dashboard/         # React SPA (Vite)
│   └── src/App.jsx    # All UI components
├── sdk/
│   ├── python/        # Python SDK
│   └── typescript/    # TypeScript SDK
├── tests/             # 100 tests
├── helm/              # Kubernetes Helm chart
├── grafana/           # Grafana dashboard template
└── docs/              # Migration guides
```

---

## What's Next

- Full feature docs: [README.md](README.md)
- Migrating from Langfuse: [docs/migrating-from-langfuse.md](docs/migrating-from-langfuse.md)
- Kubernetes deployment: [helm/agentlens/](helm/agentlens/)
- Grafana monitoring: [grafana/agentlens-dashboard.json](grafana/agentlens-dashboard.json)
