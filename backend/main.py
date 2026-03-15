"""
AgentLens Server — Production-grade FastAPI backend.

Features:
  - Structured JSON logging
  - Rate limiting middleware (token bucket)
  - Auth middleware with API key validation
  - Pydantic event validation
  - WebSocket live feed
  - Alert webhook system (with background checker)
  - Data retention / cleanup endpoint
  - DB stats / admin endpoint
  - Proper pagination with totals
  - CORS configured
  - Health check with dependency status

Run: uvicorn main:app --host 0.0.0.0 --port 8340
"""

import os
import sys
import time
import json
import asyncio
import logging
from collections import defaultdict
from typing import Optional
from contextlib import asynccontextmanager
from urllib.request import Request, urlopen

from fastapi import FastAPI, HTTPException, Header, Query, Request as FRequest, WebSocket, WebSocketDisconnect, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from pydantic import BaseModel, Field, field_validator

import database as db
from auth import AuthManager, AuthContext, ProjectManager, init_auth_tables
from encryption import encryptor, SENSITIVE_FIELDS
from retention import RetentionManager
from otel import parse_otel_traces
from anomaly import CostAnomalyDetector, compute_similarity, compute_diff
from demo_data import generate_demo_data
from metrics import record_event as metrics_record_event, render_metrics

# ─── Structured Logging ─────────────────────────────────────

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
logging.basicConfig(
    level=logging.INFO,
    format=LOG_FORMAT,
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("agentlens.server")


# ─── Rate Limiter ────────────────────────────────────────────

class RateLimiter:
    """Token bucket rate limiter. Per-IP for API, per-key for SDK."""

    def __init__(self, rate: float = 100, burst: int = 200):
        self.rate = rate        # tokens per second
        self.burst = burst      # max bucket size
        self._buckets: dict[str, tuple[float, float]] = {}  # key -> (tokens, last_time)

    def allow(self, key: str) -> bool:
        now = time.time()
        tokens, last = self._buckets.get(key, (self.burst, now))

        # Refill
        elapsed = now - last
        tokens = min(self.burst, tokens + elapsed * self.rate)

        if tokens >= 1:
            self._buckets[key] = (tokens - 1, now)
            return True
        self._buckets[key] = (tokens, now)
        return False

    def cleanup(self):
        """Remove old entries to prevent memory leak."""
        now = time.time()
        stale = [k for k, (_, t) in self._buckets.items() if now - t > 3600]
        for k in stale:
            del self._buckets[k]


rate_limiter = RateLimiter(rate=100, burst=500)  # 100 req/s, burst of 500


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to every response (SOC2/PCI readiness)."""
    async def dispatch(self, request: FRequest, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        # Strict-Transport-Security only when TLS is enabled
        if os.environ.get("AGENTLENS_TLS_CERT"):
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'"
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: FRequest, call_next):
        # Extract identifier: API key or IP
        auth = request.headers.get("authorization", "")
        key = auth if auth else (request.client.host if request.client else "unknown")

        if not rate_limiter.allow(key):
            logger.warning(f"Rate limited: {key}")
            return JSONResponse(
                status_code=429,
                content={"error": "Too many requests", "retry_after": 1},
                headers={"Retry-After": "1"},
            )

        response = await call_next(request)
        return response


# ─── Request Logging Middleware ──────────────────────────────

class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: FRequest, call_next):
        start = time.time()
        response = await call_next(request)
        elapsed = (time.time() - start) * 1000

        # Skip health checks and static files from logging
        path = request.url.path
        if path not in ("/api/health", "/metrics", "/favicon.ico") and not path.startswith("/assets"):
            logger.info(
                f"{request.method} {path} → {response.status_code} ({elapsed:.1f}ms)"
            )

        return response


# ─── WebSocket Manager ──────────────────────────────────────

class WSManager:
    """Manages WebSocket connections for live event streaming."""

    def __init__(self):
        self.connections: dict[str, list[WebSocket]] = defaultdict(list)

    async def connect(self, ws: WebSocket, project_id: str = "default"):
        await ws.accept()
        self.connections[project_id].append(ws)
        logger.info(f"WS connected: {project_id} (total: {len(self.connections[project_id])})")

    def disconnect(self, ws: WebSocket, project_id: str = "default"):
        if ws in self.connections[project_id]:
            self.connections[project_id].remove(ws)
            logger.info(f"WS disconnected: {project_id}")

    async def broadcast(self, project_id: str, data: dict):
        dead = []
        for ws in self.connections.get(project_id, []):
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws, project_id)


ws_manager = WSManager()


# ─── Alert Dispatcher ───────────────────────────────────────

async def dispatch_alerts(project_id: str = "default"):
    """Check alert conditions and fire webhooks."""
    try:
        triggered = await db.check_alert_conditions(project_id)
        for alert in triggered:
            rule = alert["rule"]
            payload = {
                "alert": rule["name"],
                "condition": rule["condition_type"],
                "threshold": rule["threshold"],
                "actual_value": alert["value"],
                "project": project_id,
                "timestamp": time.time(),
                "message": f"[AgentLens Alert] {rule['name']}: {rule['condition_type']} = {alert['value']:.2f} (threshold: {rule['threshold']})",
            }

            # Fire webhook in background
            asyncio.create_task(_fire_webhook(rule["webhook_url"], payload, rule["id"]))
            logger.warning(f"Alert triggered: {rule['name']} ({rule['condition_type']}={alert['value']:.2f})")

            # Also broadcast to WebSocket
            await ws_manager.broadcast(project_id, {
                "type": "alert",
                "data": payload,
            })
    except Exception as e:
        logger.error(f"Alert dispatch error: {e}")


async def _fire_webhook(url: str, payload: dict, rule_id: str):
    """Send webhook POST. Non-blocking."""
    loop = asyncio.get_event_loop()
    try:
        def _send():
            data = json.dumps(payload).encode("utf-8")
            req = Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
            with urlopen(req, timeout=10) as resp:
                return resp.status

        status = await loop.run_in_executor(None, _send)
        logger.info(f"Webhook fired: {url} → {status}")
    except Exception as e:
        logger.error(f"Webhook failed: {url} → {e}")


# ─── Background Tasks ───────────────────────────────────────

async def alert_checker_loop():
    """Background loop: check alert conditions every 30s."""
    while True:
        await asyncio.sleep(30)
        try:
            await dispatch_alerts("default")
        except Exception as e:
            logger.error(f"Alert checker error: {e}")


async def rate_limiter_cleanup_loop():
    """Clean up stale rate limiter entries every 10min."""
    while True:
        await asyncio.sleep(600)
        rate_limiter.cleanup()


# ─── Lifespan ────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    pool = await db.get_pool()

    # Initialize auth tables
    import sqlite3
    conn = sqlite3.connect(db.DB_PATH)
    init_auth_tables(conn)
    conn.close()

    # Initialize managers
    app.state.auth = AuthManager(pool)
    app.state.projects = ProjectManager(pool)

    # Initialize encryption at rest
    encryptor.init()
    app.state.encryption_enabled = encryptor.enabled

    # Initialize data retention
    app.state.retention = RetentionManager(pool, app.state.auth)
    await app.state.retention.init_tables()
    app.state.retention.start_background_purge()

    # Initialize cost anomaly detection
    app.state.anomaly = CostAnomalyDetector(pool)
    await app.state.anomaly.init_tables()
    app.state.anomaly.start_background_detection()

    # TLS config info
    tls_cert = os.environ.get("AGENTLENS_TLS_CERT")
    tls_key = os.environ.get("AGENTLENS_TLS_KEY")
    if tls_cert and tls_key:
        logger.info(f"TLS enabled: cert={tls_cert}")
    else:
        logger.info("TLS not configured. Set AGENTLENS_TLS_CERT and AGENTLENS_TLS_KEY for HTTPS.")

    logger.info("Server ready at http://localhost:8340")
    logger.info("Dashboard at http://localhost:8340/dashboard")

    # Start background tasks
    alert_task = asyncio.create_task(alert_checker_loop())
    cleanup_task = asyncio.create_task(rate_limiter_cleanup_loop())

    yield

    app.state.retention.stop_background_purge()
    app.state.anomaly.stop_background_detection()
    alert_task.cancel()
    cleanup_task.cancel()
    await pool.close()
    logger.info("Server shutdown complete")


app = FastAPI(
    title="AgentLens",
    description="AI Agent Observability Server — Production Grade",
    version="0.3.0",
    lifespan=lifespan,
)

# Middleware order matters — outermost first
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(RateLimitMiddleware)
# CORS: configurable via env. Default allows all for dev; restrict in production.
_cors_origins = os.environ.get("AGENTLENS_CORS_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Auth Helper ─────────────────────────────────────────────

async def resolve_auth(
    request: FRequest,
    authorization: Optional[str] = Header(None),
    x_project: Optional[str] = Header(None),
) -> AuthContext:
    """Resolve auth context from request. RBAC-aware."""
    auth_mgr: AuthManager = request.app.state.auth
    try:
        ctx = await auth_mgr.resolve(authorization, x_project)
        return ctx
    except PermissionError as e:
        raise HTTPException(status_code=401, detail=str(e))


def require_permission(permission: str):
    """Dependency that checks a specific permission."""
    async def _check(auth: AuthContext = Depends(resolve_auth)):
        if not auth.has_permission(permission):
            raise HTTPException(
                status_code=403,
                detail=f"Insufficient permissions. Required: {permission}, role: {auth.role.value}"
            )
        return auth
    return _check


# ─── Pydantic Models ────────────────────────────────────────

VALID_EVENT_TYPES = {
    "session.start", "session.end",
    "llm.request", "llm.response", "llm.error",
    "tool.call", "tool.result", "tool.error",
    "agent.step", "agent.decision", "agent.thought",
    "custom", "error", "guardrail.triggered",
}


class EventItem(BaseModel):
    event_type: str
    event_id: Optional[str] = None
    timestamp: Optional[float] = None
    session_id: Optional[str] = ""
    agent_name: Optional[str] = "unknown"
    project_id: Optional[str] = ""
    model: Optional[str] = None
    provider: Optional[str] = None
    prompt: Optional[str] = None
    completion: Optional[str] = None
    input_tokens: Optional[int] = Field(None, ge=0)
    output_tokens: Optional[int] = Field(None, ge=0)
    total_tokens: Optional[int] = Field(None, ge=0)
    cost_usd: Optional[float] = Field(None, ge=0)
    latency_ms: Optional[float] = Field(None, ge=0)
    tool_name: Optional[str] = None
    tool_args: Optional[dict] = None
    tool_result: Optional[str] = None
    thought: Optional[str] = None
    decision: Optional[str] = None
    step_number: Optional[int] = None
    error_message: Optional[str] = None
    error_type: Optional[str] = None
    stack_trace: Optional[str] = None
    success: Optional[bool] = None
    duration_ms: Optional[float] = None
    parent_id: Optional[str] = None
    user_id: Optional[str] = None
    tags: Optional[dict] = None
    meta: Optional[dict] = None

    @field_validator("event_type")
    @classmethod
    def validate_event_type(cls, v):
        if v not in VALID_EVENT_TYPES:
            raise ValueError(f"Invalid event_type: {v}. Must be one of: {VALID_EVENT_TYPES}")
        return v


class EventBatch(BaseModel):
    events: list[dict]  # Accept dicts for backward compat, validate below


class AlertRuleCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    condition_type: str = Field(..., pattern="^(error_rate|latency|cost|failure_streak)$")
    threshold: float = Field(..., gt=0)
    webhook_url: str = Field(..., min_length=10)
    window_minutes: int = Field(5, ge=1, le=1440)
    cooldown_minutes: int = Field(15, ge=1, le=1440)


# ─── Event Ingestion ─────────────────────────────────────────

@app.post("/api/v1/events")
async def ingest_events(
    batch: EventBatch,
    request: FRequest,
    auth: AuthContext = Depends(require_permission("events.ingest")),
):
    """Receive a batch of events from the SDK. Validates, stores, broadcasts."""
    project_id = auth.project_id

    # Validate events
    valid_events = []
    errors = []
    for i, raw_event in enumerate(batch.events):
        try:
            # Validate through Pydantic
            EventItem(**raw_event)
            valid_events.append(raw_event)  # Store original dict
        except Exception as e:
            errors.append({"index": i, "error": str(e)})
            logger.warning(f"Invalid event at index {i}: {e}")

    if not valid_events:
        raise HTTPException(status_code=400, detail={"error": "No valid events", "validation_errors": errors})

    try:
        # Encrypt sensitive fields before storage
        encrypted_events = [encryptor.encrypt_event(e) for e in valid_events]
        count = await db.insert_events(encrypted_events, project_id)

        # Broadcast to WebSocket clients
        for event in valid_events:
            await ws_manager.broadcast(project_id, {"type": "event", "data": event})
            # Update Prometheus metrics
            metrics_record_event(event)

        # Check alerts after ingestion
        asyncio.create_task(dispatch_alerts(project_id))

        response = {"ok": True, "inserted": count}
        if errors:
            response["validation_errors"] = errors
            response["skipped"] = len(errors)

        return response
    except Exception as e:
        logger.error(f"Event ingestion error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ─── Sessions API ────────────────────────────────────────────

@app.get("/api/v1/sessions")
async def list_sessions(
    agent: Optional[str] = None,
    user: Optional[str] = None,
    limit: int = Query(50, le=500),
    offset: int = 0,
    auth: AuthContext = Depends(require_permission("sessions.read")),
):
    project_id = auth.project_id
    sessions, total = await db.get_sessions(
        project_id, agent_name=agent, user_id=user, limit=limit, offset=offset
    )
    return {
        "sessions": sessions,
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": offset + limit < total,
    }


@app.get("/api/v1/sessions/{session_id}")
async def get_session(
    session_id: str,
    auth: AuthContext = Depends(require_permission("sessions.read")),
):
    session = await db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    events = await db.get_session_events(session_id)
    session["events"] = encryptor.decrypt_events(events)
    return session


# ─── Events API ──────────────────────────────────────────────

@app.get("/api/v1/events")
async def list_events(
    event_type: Optional[str] = None,
    limit: int = Query(100, le=1000),
    since: Optional[float] = None,
    auth: AuthContext = Depends(require_permission("events.read")),
):
    project_id = auth.project_id
    events = await db.get_events(project_id, event_type=event_type, limit=limit, since=since)
    decrypted = encryptor.decrypt_events(events)
    return {"events": decrypted, "total": len(decrypted)}


# ─── Analytics API ───────────────────────────────────────────

@app.get("/api/v1/analytics")
async def get_analytics(
    hours: int = Query(24, le=720),
    auth: AuthContext = Depends(require_permission("analytics.read")),
):
    project_id = auth.project_id
    return await db.get_analytics(project_id, hours=hours)


# ─── Live Feed (WebSocket) ──────────────────────────────────

@app.websocket("/ws/live")
async def websocket_live(
    ws: WebSocket,
    project: str = "default",
):
    """WebSocket endpoint for real-time event streaming."""
    await ws_manager.connect(ws, project)
    try:
        while True:
            # Keep connection alive, receive pings
            data = await ws.receive_text()
            if data == "ping":
                await ws.send_text("pong")
    except WebSocketDisconnect:
        ws_manager.disconnect(ws, project)
    except Exception:
        ws_manager.disconnect(ws, project)


# ─── Live Feed (Polling fallback) ───────────────────────────

@app.get("/api/v1/live")
async def live_events(
    auth: AuthContext = Depends(require_permission("events.read")),
):
    """Polling fallback for live view. Get last 60s of events."""
    project_id = auth.project_id
    events = await db.get_events(project_id, limit=20, since=time.time() - 60)
    return {"events": encryptor.decrypt_events(events)}


# ─── Alert Rules API ────────────────────────────────────────

@app.post("/api/v1/alerts")
async def create_alert(
    rule: AlertRuleCreate,
    auth: AuthContext = Depends(require_permission("alerts.create")),
):
    """Create an alert rule. Fires webhook when condition is met."""
    project_id = auth.project_id
    result = await db.create_alert_rule(
        project_id=project_id,
        name=rule.name,
        condition_type=rule.condition_type,
        threshold=rule.threshold,
        webhook_url=rule.webhook_url,
        window_minutes=rule.window_minutes,
        cooldown_minutes=rule.cooldown_minutes,
    )
    logger.info(f"Alert rule created: {rule.name} ({rule.condition_type} >= {rule.threshold})")
    return result


@app.get("/api/v1/alerts")
async def list_alerts(
    auth: AuthContext = Depends(require_permission("alerts.read")),
):
    project_id = auth.project_id
    rules = await db.get_alert_rules(project_id)
    history = await db.get_alert_history(project_id, limit=20)
    return {"rules": rules, "recent_alerts": history}


@app.delete("/api/v1/alerts/{rule_id}")
async def delete_alert(rule_id: str):
    await db.delete_alert_rule(rule_id)
    return {"ok": True}


# ─── Admin API ───────────────────────────────────────────────

@app.get("/api/v1/admin/stats")
async def admin_stats(auth: AuthContext = Depends(require_permission("admin.stats"))):
    """Database stats for monitoring."""
    return await db.get_db_stats()


@app.post("/api/v1/admin/cleanup")
async def admin_cleanup(
    request: FRequest,
    days: int = Query(30, ge=1, le=365),
    auth: AuthContext = Depends(require_permission("admin.cleanup")),
):
    """Delete events/sessions older than N days."""
    result = await db.cleanup_old_data(days)
    logger.info(f"Cleanup executed by {auth.key_name}: {result}")
    await request.app.state.auth.log_action("admin.cleanup", auth, details=json.dumps(result))
    return result


# ─── Health ──────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    """Health check with dependency status."""
    db_ok = True
    try:
        stats = await db.get_db_stats()
    except Exception:
        db_ok = False
        stats = {}

    return {
        "status": "ok" if db_ok else "degraded",
        "version": "0.3.0",
        "timestamp": time.time(),
        "dependencies": {
            "database": "ok" if db_ok else "error",
        },
        "security": {
            "encryption_at_rest": encryptor.enabled,
            "tls": bool(os.environ.get("AGENTLENS_TLS_CERT")),
            "rbac": True,
            "pii_redaction": True,
            "audit_logging": True,
            "data_retention": True,
            "security_headers": True,
        },
        "db": stats,
        "ws_connections": sum(len(v) for v in ws_manager.connections.values()),
    }


# ─── Prometheus Metrics ─────────────────────────────────────

@app.get("/metrics")
async def prometheus_metrics():
    """Prometheus-compatible metrics endpoint. No auth required (standard practice)."""
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(render_metrics(), media_type="text/plain; version=0.0.4; charset=utf-8")


# ─── Dashboard (serve React build) ──────────────────────────

DASHBOARD_DIR = os.path.join(os.path.dirname(__file__), "..", "dashboard", "dist")

if os.path.exists(DASHBOARD_DIR):
    app.mount("/assets", StaticFiles(directory=os.path.join(DASHBOARD_DIR, "assets")), name="assets")

    @app.get("/dashboard/{rest_of_path:path}")
    async def dashboard(rest_of_path: str = ""):
        return FileResponse(os.path.join(DASHBOARD_DIR, "index.html"))

    @app.get("/dashboard")
    async def dashboard_root():
        return FileResponse(os.path.join(DASHBOARD_DIR, "index.html"))


# ─── Root ────────────────────────────────────────────────────

@app.get("/")
async def root():
    return {
        "name": "AgentLens",
        "version": "0.3.0",
        "docs": "/docs",
        "dashboard": "/dashboard",
        "api": {
            "events": "/api/v1/events",
            "sessions": "/api/v1/sessions",
            "analytics": "/api/v1/analytics",
            "alerts": "/api/v1/alerts",
            "live_ws": "/ws/live",
            "live_poll": "/api/v1/live",
            "admin_stats": "/api/v1/admin/stats",
            "admin_cleanup": "/api/v1/admin/cleanup",
            "keys": "/api/v1/keys",
            "keys_rotate": "/api/v1/keys/{key_id}/rotate",
            "projects": "/api/v1/projects",
            "retention": "/api/v1/retention",
            "retention_purge": "/api/v1/retention/purge",
            "encryption_status": "/api/v1/admin/encryption",
            "audit": "/api/v1/audit",
            "health": "/api/health",
        },
    }


# ─── API Key Management ─────────────────────────────────────

class CreateKeyRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    role: str = Field("member", pattern="^(admin|member|viewer)$")
    expires_days: Optional[int] = Field(None, ge=1, le=365)


@app.post("/api/v1/keys")
async def create_api_key(
    req: CreateKeyRequest,
    request: FRequest,
    auth: AuthContext = Depends(require_permission("admin.manage_keys")),
):
    """Create a new API key. The plaintext key is only returned once."""
    result = await request.app.state.auth.create_key(
        project_id=auth.project_id,
        name=req.name,
        role=req.role,
        expires_days=req.expires_days,
        created_by=auth.key_id,
    )
    await request.app.state.auth.log_action(
        "key.create", auth, resource="api_key", resource_id=result["id"]
    )
    return result


@app.get("/api/v1/keys")
async def list_api_keys(
    request: FRequest,
    auth: AuthContext = Depends(require_permission("admin.manage_keys")),
):
    """List all API keys for the project (no secrets exposed)."""
    return {"keys": await request.app.state.auth.list_keys(auth.project_id)}


@app.delete("/api/v1/keys/{key_id}")
async def revoke_api_key(
    key_id: str,
    request: FRequest,
    auth: AuthContext = Depends(require_permission("admin.manage_keys")),
):
    """Revoke an API key."""
    await request.app.state.auth.revoke_key(key_id, auth.project_id)
    await request.app.state.auth.log_action(
        "key.revoke", auth, resource="api_key", resource_id=key_id
    )
    return {"ok": True, "revoked": key_id}


# ─── Project Management ─────────────────────────────────────

class CreateProjectRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    settings: Optional[dict] = None


@app.post("/api/v1/projects")
async def create_project(
    req: CreateProjectRequest,
    request: FRequest,
    auth: AuthContext = Depends(require_permission("projects.create")),
):
    """Create a new project with isolated data."""
    result = await request.app.state.projects.create_project(req.name, req.settings)
    # Auto-create an admin key for the new project
    key = await request.app.state.auth.create_key(
        project_id=result["id"], name="Auto Admin Key", role="admin", created_by=auth.key_id
    )
    result["admin_key"] = key["key"]  # Show once
    await request.app.state.auth.log_action(
        "project.create", auth, resource="project", resource_id=result["id"]
    )
    return result


@app.get("/api/v1/projects")
async def list_projects(
    request: FRequest,
    auth: AuthContext = Depends(require_permission("projects.read")),
):
    return {"projects": await request.app.state.projects.list_projects()}


@app.delete("/api/v1/projects/{project_id}")
async def delete_project(
    project_id: str,
    request: FRequest,
    auth: AuthContext = Depends(require_permission("projects.delete")),
):
    """Delete a project and ALL its data. Irreversible."""
    try:
        result = await request.app.state.projects.delete_project(project_id)
        await request.app.state.auth.log_action(
            "project.delete", auth, resource="project", resource_id=project_id,
            details=json.dumps(result),
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ─── Audit Log ───────────────────────────────────────────────

@app.get("/api/v1/audit")
async def get_audit_log(
    request: FRequest,
    limit: int = Query(100, le=1000),
    action: Optional[str] = None,
    auth: AuthContext = Depends(require_permission("admin.stats")),
):
    """View audit log of all admin actions."""
    entries = await request.app.state.auth.get_audit_log(auth.project_id, limit, action)
    return {"entries": entries, "total": len(entries)}


# ─── Key Rotation ────────────────────────────────────────────

class RotateKeyRequest(BaseModel):
    grace_period_hours: int = Field(24, ge=1, le=720)


@app.post("/api/v1/keys/{key_id}/rotate")
async def rotate_api_key(
    key_id: str,
    req: RotateKeyRequest,
    request: FRequest,
    auth: AuthContext = Depends(require_permission("admin.manage_keys")),
):
    """Rotate an API key. Old key works during grace period, then expires."""
    try:
        result = await request.app.state.auth.rotate_key(
            key_id, auth.project_id, req.grace_period_hours
        )
        await request.app.state.auth.log_action(
            "key.rotate", auth, resource="api_key", resource_id=key_id,
            details=json.dumps({"new_key_id": result["new_key"]["id"]}),
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/api/v1/keys/rotate-all")
async def rotate_all_keys(
    req: RotateKeyRequest,
    request: FRequest,
    auth: AuthContext = Depends(require_permission("admin.manage_keys")),
):
    """Rotate ALL active keys for the project."""
    results = await request.app.state.auth.rotate_all_project_keys(
        auth.project_id, req.grace_period_hours
    )
    await request.app.state.auth.log_action(
        "key.rotate_all", auth, resource="api_key",
        details=json.dumps({"rotated": len(results)}),
    )
    return {"rotated": results, "total": len(results)}


# ─── Data Retention API ──────────────────────────────────────

class RetentionPolicyRequest(BaseModel):
    retention_days: int = Field(..., ge=1, le=3650)
    delete_events: bool = True
    delete_sessions: bool = True
    delete_audit_logs: bool = False


@app.get("/api/v1/retention")
async def get_retention_policy(
    request: FRequest,
    auth: AuthContext = Depends(require_permission("admin.stats")),
):
    """Get data retention policy for the project."""
    policy = await request.app.state.retention.get_policy(auth.project_id)
    return {"policy": policy}


@app.put("/api/v1/retention")
async def set_retention_policy(
    req: RetentionPolicyRequest,
    request: FRequest,
    auth: AuthContext = Depends(require_permission("admin.manage_keys")),
):
    """Set data retention policy for the project."""
    result = await request.app.state.retention.set_policy(
        auth.project_id,
        retention_days=req.retention_days,
        delete_events=req.delete_events,
        delete_sessions=req.delete_sessions,
        delete_audit_logs=req.delete_audit_logs,
    )
    await request.app.state.auth.log_action(
        "retention.set_policy", auth, resource="retention",
        details=json.dumps({"retention_days": req.retention_days}),
    )
    return result


@app.post("/api/v1/retention/purge")
async def trigger_retention_purge(
    request: FRequest,
    auth: AuthContext = Depends(require_permission("admin.cleanup")),
):
    """Manually trigger data retention purge for the project."""
    result = await request.app.state.retention.purge_project(auth.project_id)
    await request.app.state.auth.log_action(
        "retention.purge", auth, resource="retention",
        details=json.dumps(result),
    )
    return result


@app.get("/api/v1/retention/history")
async def get_retention_history(
    request: FRequest,
    limit: int = Query(50, le=500),
    auth: AuthContext = Depends(require_permission("admin.stats")),
):
    """Get history of retention purges."""
    history = await request.app.state.retention.get_purge_history(auth.project_id, limit)
    return {"history": history, "total": len(history)}


# ─── Encryption Status ───────────────────────────────────────

@app.get("/api/v1/admin/encryption")
async def encryption_status(
    auth: AuthContext = Depends(require_permission("admin.stats")),
):
    """Get encryption status and security posture."""
    return {
        "encryption_at_rest": encryptor.enabled,
        "algorithm": "AES-128-CBC + HMAC-SHA256 (Fernet)" if encryptor.enabled else None,
        "encrypted_fields": list(SENSITIVE_FIELDS) if encryptor.enabled else [],
        "tls_configured": bool(os.environ.get("AGENTLENS_TLS_CERT")),
        "security_headers": True,
        "rbac_enabled": True,
        "audit_logging": True,
    }


# ─── OpenTelemetry Ingestion ─────────────────────────────────

@app.post("/api/v1/otel/traces")
@app.post("/v1/traces")
async def ingest_otel_traces(
    request: FRequest,
    auth: AuthContext = Depends(require_permission("events.ingest")),
):
    """Accept OTLP JSON traces and convert to AgentLens events.

    Compatible with OTEL exporters: set endpoint to http://localhost:8340/v1/traces
    """
    body = await request.json()
    events = parse_otel_traces(body)

    if not events:
        return {"ok": True, "inserted": 0, "message": "No spans found in payload"}

    project_id = auth.project_id
    encrypted_events = [encryptor.encrypt_event(e) for e in events]
    count = await db.insert_events(encrypted_events, project_id)

    # Broadcast to WebSocket
    for event in events:
        await ws_manager.broadcast(project_id, {"type": "event", "data": event})

    asyncio.create_task(dispatch_alerts(project_id))

    return {"ok": True, "inserted": count, "spans_received": len(events)}


# ─── Trace Tree (Nested Span Hierarchy) ──────────────────────

@app.get("/api/v1/traces/{trace_id}")
async def get_trace_tree(
    trace_id: str,
    auth: AuthContext = Depends(require_permission("events.read")),
):
    """Get a full trace as a nested tree structure.

    Returns events organized by parent_id into a tree hierarchy
    with timing info for waterfall visualization.
    """
    # Direct query — efficient: only events for this session
    trace_events = await db.get_session_events(trace_id)

    if not trace_events:
        # Fallback: try as OTEL trace_id in meta
        project_id = auth.project_id
        all_events = await db.get_events(project_id, limit=5000)
        trace_events = []
        for e in all_events:
            meta = e.get("meta", "{}")
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except (json.JSONDecodeError, ValueError):
                    meta = {}
            if meta.get("otel_trace_id") == trace_id:
                trace_events.append(e)

    if not trace_events:
        raise HTTPException(status_code=404, detail="Trace not found")

    # Decrypt
    trace_events = encryptor.decrypt_events(trace_events)

    # Sort by timestamp
    trace_events.sort(key=lambda e: e.get("timestamp", 0))

    # Build tree using parent_id → children
    by_id = {}
    for e in trace_events:
        eid = e.get("id") or e.get("event_id", "")
        by_id[eid] = e
        e["children"] = []

    roots = []
    for event in trace_events:
        parent_id = event.get("parent_id", "")
        if parent_id and parent_id in by_id:
            by_id[parent_id]["children"].append(event)
        else:
            roots.append(event)

    # Calculate trace-level stats
    min_time = min(e.get("timestamp", float("inf")) for e in trace_events)
    max_time = max(e.get("timestamp", 0) for e in trace_events)
    total_cost = sum(e.get("cost_usd", 0) or 0 for e in trace_events)
    total_tokens = sum(e.get("total_tokens", 0) or 0 for e in trace_events)

    # Compute duration_ms for container spans that lack it
    def compute_duration(node):
        """Walk tree bottom-up: parent duration = max(child end) - parent start."""
        child_max = 0
        for child in node.get("children", []):
            compute_duration(child)
            child_end = ((child.get("timestamp", 0) - min_time) * 1000
                        + (child.get("duration_ms") or child.get("latency_ms") or 0))
            if child_end > child_max:
                child_max = child_end
        # If this node has no duration yet, infer from children
        if not node.get("duration_ms") and not node.get("latency_ms") and child_max > 0:
            node_start_ms = (node.get("timestamp", 0) - min_time) * 1000
            node["duration_ms"] = round(child_max - node_start_ms, 1)

    for root in roots:
        compute_duration(root)

    return {
        "trace_id": trace_id,
        "root_spans": roots,
        "all_events": trace_events,
        "stats": {
            "total_events": len(trace_events),
            "total_duration_ms": round((max_time - min_time) * 1000, 1),
            "total_cost_usd": round(total_cost, 6),
            "total_tokens": total_tokens,
            "start_time": min_time,
            "end_time": max_time,
        },
    }


# ─── Prompt Diff / Replay ────────────────────────────────────

@app.get("/api/v1/events/{event_id}/detail")
async def get_event_detail(
    event_id: str,
    auth: AuthContext = Depends(require_permission("events.read")),
):
    """Get full event detail with prompt/completion and similar events for diffing."""
    pool = await db.get_pool()
    event = await pool.fetchone(
        "SELECT * FROM events WHERE id = ? AND project_id = ?",
        (event_id, auth.project_id),
    )
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    event = encryptor.decrypt_event(dict(event))

    # Find similar LLM calls for diff comparison
    similar = []
    if event.get("event_type") == "llm.response" and event.get("prompt"):
        recent_llm = await pool.fetchall(
            """SELECT id, prompt, completion, model, cost_usd, latency_ms, success, timestamp
               FROM events
               WHERE project_id = ? AND event_type = 'llm.response'
                 AND id != ? AND prompt IS NOT NULL
               ORDER BY timestamp DESC LIMIT 50""",
            (auth.project_id, event_id),
        )

        for other in recent_llm:
            other = encryptor.decrypt_event(dict(other))
            sim = compute_similarity(event.get("prompt", ""), other.get("prompt", ""))
            if sim > 0.3:  # At least 30% similar
                similar.append({
                    "event_id": other["id"],
                    "similarity": round(sim * 100, 1),
                    "model": other.get("model"),
                    "success": other.get("success"),
                    "cost_usd": other.get("cost_usd"),
                    "timestamp": other.get("timestamp"),
                })

        # Sort by similarity descending
        similar.sort(key=lambda x: x["similarity"], reverse=True)
        similar = similar[:10]

    return {
        "event": event,
        "similar_prompts": similar,
    }


@app.get("/api/v1/events/{event_id}/diff/{other_event_id}")
async def diff_events(
    event_id: str,
    other_event_id: str,
    auth: AuthContext = Depends(require_permission("events.read")),
):
    """Compute diff between two LLM call prompts/completions."""
    pool = await db.get_pool()

    event_a = await pool.fetchone(
        "SELECT * FROM events WHERE id = ? AND project_id = ?",
        (event_id, auth.project_id),
    )
    event_b = await pool.fetchone(
        "SELECT * FROM events WHERE id = ? AND project_id = ?",
        (other_event_id, auth.project_id),
    )

    if not event_a or not event_b:
        raise HTTPException(status_code=404, detail="Event not found")

    event_a = encryptor.decrypt_event(dict(event_a))
    event_b = encryptor.decrypt_event(dict(event_b))

    prompt_sim = compute_similarity(event_a.get("prompt", ""), event_b.get("prompt", ""))
    completion_sim = compute_similarity(event_a.get("completion", ""), event_b.get("completion", ""))
    prompt_diff = compute_diff(event_a.get("prompt", ""), event_b.get("prompt", ""))
    completion_diff = compute_diff(event_a.get("completion", ""), event_b.get("completion", ""))

    return {
        "event_a": {"id": event_id, "model": event_a.get("model"), "success": event_a.get("success"),
                     "cost_usd": event_a.get("cost_usd"), "timestamp": event_a.get("timestamp")},
        "event_b": {"id": other_event_id, "model": event_b.get("model"), "success": event_b.get("success"),
                     "cost_usd": event_b.get("cost_usd"), "timestamp": event_b.get("timestamp")},
        "prompt_similarity": round(prompt_sim * 100, 1),
        "completion_similarity": round(completion_sim * 100, 1),
        "prompt_diff": prompt_diff,
        "completion_diff": completion_diff,
    }


# ─── Cost Anomaly Detection API ──────────────────────────────

@app.get("/api/v1/anomalies")
async def get_cost_anomalies(
    request: FRequest,
    limit: int = Query(50, le=500),
    auth: AuthContext = Depends(require_permission("analytics.read")),
):
    """Get detected cost anomalies. Zero-config — runs automatically."""
    anomalies = await request.app.state.anomaly.get_anomalies(auth.project_id, limit)
    return {"anomalies": anomalies, "total": len(anomalies)}


@app.get("/api/v1/anomalies/trends")
async def get_cost_trends(
    request: FRequest,
    days: int = Query(30, le=365),
    auth: AuthContext = Depends(require_permission("analytics.read")),
):
    """Get daily cost trends per agent for visualization."""
    trends = await request.app.state.anomaly.get_cost_trends(auth.project_id, days)
    return {"trends": trends}


@app.post("/api/v1/anomalies/{anomaly_id}/acknowledge")
async def acknowledge_anomaly(
    anomaly_id: int,
    request: FRequest,
    auth: AuthContext = Depends(require_permission("alerts.create")),
):
    """Acknowledge a cost anomaly."""
    await request.app.state.anomaly.acknowledge_anomaly(anomaly_id)
    return {"ok": True}


@app.post("/api/v1/anomalies/detect")
async def trigger_anomaly_detection(
    request: FRequest,
    auth: AuthContext = Depends(require_permission("admin.stats")),
):
    """Manually trigger cost anomaly detection."""
    await request.app.state.anomaly.update_baselines(auth.project_id)
    anomalies = await request.app.state.anomaly.detect_anomalies(auth.project_id)
    return {"anomalies_detected": len(anomalies), "anomalies": anomalies}


# ─── Demo Data ───────────────────────────────────────────────

@app.post("/api/v1/demo/load")
async def load_demo_data(
    request: FRequest,
    auth: AuthContext = Depends(require_permission("events.ingest")),
):
    """Load ~500 realistic demo events across 5 agent types.

    Includes one agent with cost spikes and one with high error rate.
    """
    project_id = auth.project_id
    events = generate_demo_data()

    encrypted_events = [encryptor.encrypt_event(e) for e in events]
    count = await db.insert_events(encrypted_events, project_id)

    # Update anomaly baselines with new data
    try:
        await request.app.state.anomaly.update_baselines(project_id)
    except Exception:
        pass

    return {
        "ok": True,
        "inserted": count,
        "total_events": len(events),
        "agents": ["CustomerSupportBot", "ResearchAgent", "CodeReviewAgent",
                    "DataPipelineAgent", "ChatBot"],
        "message": "Demo data loaded! Refresh the dashboard to see it.",
    }


# ─── Agent Graph (DAG) ───────────────────────────────────────

@app.get("/api/v1/sessions/{session_id}/graph")
async def get_session_graph(
    session_id: str,
    auth: AuthContext = Depends(require_permission("sessions.read")),
):
    """Get agent execution graph (DAG) for a session.

    Returns a clean execution-flow DAG:
      session.start → step[1] → step[2] → ... → session.end
                        ↓          ↓
                       llm        llm
                       tool       tool

    Nodes have a ``role`` field: "spine" (main flow) or "leaf" (children).
    """
    events = await db.get_session_events(session_id)
    if not events:
        raise HTTPException(status_code=404, detail="Session not found")

    events = encryptor.decrypt_events(events)
    events.sort(key=lambda e: e.get("timestamp", 0))

    agents_seen = set()

    def _status(event):
        s = event.get("success")
        et = event.get("event_type", "")
        if s is True or s == 1:
            return "success"
        if s is False or s == 0:
            return "error"
        if "error" in et:
            return "error"
        return "running" if et.endswith(".start") else "success"

    def _node(event, role="spine"):
        eid = event.get("id") or event.get("event_id", "")
        etype = event.get("event_type", "")
        agent = event.get("agent_name", "unknown")
        agents_seen.add(agent)
        cost = event.get("cost_usd") or 0
        tokens = event.get("total_tokens") or 0
        dur = event.get("duration_ms") or event.get("latency_ms") or 0

        # Readable label
        if "session.start" in etype:
            label = agent
        elif "session.end" in etype:
            label = "done" if event.get("success") else "failed"
        elif "agent.step" in etype:
            step_n = event.get("step_number", "?")
            decision = (event.get("decision") or event.get("thought") or "")[:30]
            label = f"step {step_n}: {decision}" if decision else f"step {step_n}"
        elif event.get("tool_name"):
            label = event["tool_name"]
        elif event.get("model"):
            label = event["model"]
        else:
            label = etype.split(".")[-1]

        return {
            "id": eid,
            "type": etype,
            "agent": agent,
            "label": label,
            "status": _status(event),
            "role": role,
            "parent_id": event.get("parent_id", ""),
            "timestamp": event.get("timestamp"),
            "duration_ms": round(dur, 1) if dur else None,
            "cost_usd": round(cost, 6) if cost else None,
            "tokens": tokens or None,
        }

    # ── Classify events ──
    session_start = None
    session_end = None
    steps = []        # agent.step in order
    leaf_events = []  # llm/tool/error events

    for ev in events:
        et = ev.get("event_type", "")
        if "session.start" in et:
            session_start = ev
        elif "session.end" in et:
            session_end = ev
        elif "agent.step" in et:
            steps.append(ev)
        else:
            leaf_events.append(ev)

    nodes = []
    edges = []

    # ── Spine: session.start → step1 → step2 → ... → session.end ──
    spine_ids = []

    if session_start:
        n = _node(session_start, "spine")
        nodes.append(n)
        spine_ids.append(n["id"])

    for step in steps:
        n = _node(step, "spine")
        nodes.append(n)
        spine_ids.append(n["id"])

    if session_end:
        n = _node(session_end, "spine")
        nodes.append(n)
        spine_ids.append(n["id"])

    # Sequential edges along the spine
    for i in range(len(spine_ids) - 1):
        edges.append({"from": spine_ids[i], "to": spine_ids[i + 1], "type": "flow"})

    # ── Leaves: attach to their parent step ──
    step_id_set = {s.get("id") or s.get("event_id", "") for s in steps}
    start_id = (session_start.get("id") or session_start.get("event_id", "")) if session_start else ""

    for ev in leaf_events:
        n = _node(ev, "leaf")
        pid = n["parent_id"]
        # Only attach if parent is a step or session.start
        if pid in step_id_set or pid == start_id:
            nodes.append(n)
            edges.append({"from": pid, "to": n["id"], "type": "child"})

    # ── Fallback: if no steps found, make sequential chain ──
    if not steps and len(nodes) > 1:
        for i in range(len(nodes) - 1):
            edges.append({"from": nodes[i]["id"], "to": nodes[i + 1]["id"], "type": "flow"})

    return {
        "session_id": session_id,
        "nodes": nodes,
        "edges": edges,
        "agents": list(agents_seen),
        "stats": {
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "unique_agents": len(agents_seen),
        },
    }

