"""
Backend Integration Tests — tests the FastAPI server end-to-end.
Uses httpx + pytest-asyncio to test all API endpoints.
"""

import os
import sys
import time
import json
import uuid
import tempfile

import pytest

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "backend"))

# Use a temp database for tests
TEST_DB = os.path.join(tempfile.gettempdir(), f"agentlens_test_{uuid.uuid4().hex[:8]}.db")
os.environ["AGENTLENS_DB"] = TEST_DB

from httpx import AsyncClient, ASGITransport
from main import app
import database as db_module
from auth import AuthManager, ProjectManager, init_auth_tables
from encryption import encryptor
from retention import RetentionManager
from anomaly import CostAnomalyDetector
import sqlite3


@pytest.fixture(scope="module")
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="module")
async def client():
    """Create test client with proper initialization (simulating lifespan)."""
    # Initialize DB
    db_module.init_db()
    pool = await db_module.get_pool()

    # Initialize auth tables
    conn = sqlite3.connect(TEST_DB)
    init_auth_tables(conn)
    conn.close()

    # Initialize encryption
    encryptor.init()

    # Set app state (normally done in lifespan)
    app.state.auth = AuthManager(pool)
    app.state.projects = ProjectManager(pool)
    app.state.retention = RetentionManager(pool, app.state.auth)
    await app.state.retention.init_tables()
    app.state.encryption_enabled = encryptor.enabled

    # Initialize anomaly detector
    app.state.anomaly = CostAnomalyDetector(pool)
    await app.state.anomaly.init_tables()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    # Cleanup
    await pool.close()
    db_module.pool = None
    for f in [TEST_DB, TEST_DB + "-shm", TEST_DB + "-wal"]:
        if os.path.exists(f):
            try:
                os.remove(f)
            except Exception:
                pass


# ─── Health Tests ────────────────────────────────────────────

@pytest.mark.anyio
async def test_health(client):
    res = await client.get("/api/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] in ("ok", "degraded")
    assert "version" in data
    assert data["version"] == "0.3.0"


@pytest.mark.anyio
async def test_root(client):
    res = await client.get("/")
    assert res.status_code == 200
    data = res.json()
    assert data["name"] == "AgentLens"
    assert "api" in data


# ─── Event Ingestion Tests ──────────────────────────────────

@pytest.mark.anyio
async def test_ingest_single_event(client):
    res = await client.post("/api/v1/events", json={
        "events": [{
            "event_type": "llm.response",
            "event_id": f"test_{uuid.uuid4().hex[:8]}",
            "session_id": "test-session-1",
            "agent_name": "test-agent",
            "timestamp": time.time(),
            "model": "gpt-4o",
            "input_tokens": 100,
            "output_tokens": 50,
        }]
    })
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert data["inserted"] == 1


@pytest.mark.anyio
async def test_ingest_batch(client):
    events = []
    session_id = f"batch-session-{uuid.uuid4().hex[:8]}"
    events.append({
        "event_type": "session.start",
        "event_id": f"evt_{uuid.uuid4().hex[:8]}",
        "session_id": session_id,
        "agent_name": "batch-agent",
        "timestamp": time.time(),
    })
    for i in range(5):
        events.append({
            "event_type": "llm.response",
            "event_id": f"evt_{uuid.uuid4().hex[:8]}",
            "session_id": session_id,
            "agent_name": "batch-agent",
            "timestamp": time.time() + i,
            "model": "gpt-4o-mini",
            "input_tokens": 50 + i * 10,
            "output_tokens": 25 + i * 5,
            "cost_usd": 0.001 * (i + 1),
        })
    events.append({
        "event_type": "session.end",
        "event_id": f"evt_{uuid.uuid4().hex[:8]}",
        "session_id": session_id,
        "agent_name": "batch-agent",
        "timestamp": time.time() + 6,
        "success": True,
        "meta": {"total_cost": 0.015, "total_tokens": 500, "llm_calls": 5},
    })

    res = await client.post("/api/v1/events", json={"events": events})
    assert res.status_code == 200
    assert res.json()["inserted"] == 7


@pytest.mark.anyio
async def test_ingest_invalid_event_type(client):
    res = await client.post("/api/v1/events", json={
        "events": [{"event_type": "INVALID_TYPE", "timestamp": time.time()}]
    })
    # Should return 400 since no valid events
    assert res.status_code == 400


@pytest.mark.anyio
async def test_ingest_empty_batch(client):
    res = await client.post("/api/v1/events", json={"events": []})
    assert res.status_code == 400


# ─── Sessions API Tests ─────────────────────────────────────

@pytest.mark.anyio
async def test_list_sessions(client):
    res = await client.get("/api/v1/sessions")
    assert res.status_code == 200
    data = res.json()
    assert "sessions" in data
    assert "total" in data
    assert isinstance(data["sessions"], list)


@pytest.mark.anyio
async def test_list_sessions_with_filter(client):
    res = await client.get("/api/v1/sessions?agent=batch-agent")
    assert res.status_code == 200
    data = res.json()
    for s in data["sessions"]:
        assert s["agent_name"] == "batch-agent"


@pytest.mark.anyio
async def test_list_sessions_pagination(client):
    res = await client.get("/api/v1/sessions?limit=1&offset=0")
    assert res.status_code == 200
    data = res.json()
    assert data["limit"] == 1
    assert len(data["sessions"]) <= 1


# ─── Events API Tests ───────────────────────────────────────

@pytest.mark.anyio
async def test_list_events(client):
    res = await client.get("/api/v1/events")
    assert res.status_code == 200
    data = res.json()
    assert "events" in data
    assert isinstance(data["events"], list)


@pytest.mark.anyio
async def test_list_events_by_type(client):
    res = await client.get("/api/v1/events?event_type=llm.response")
    assert res.status_code == 200
    for e in res.json()["events"]:
        assert e["event_type"] == "llm.response"


# ─── Analytics API Tests ────────────────────────────────────

@pytest.mark.anyio
async def test_analytics(client):
    res = await client.get("/api/v1/analytics?hours=24")
    assert res.status_code == 200
    data = res.json()
    assert "total_sessions" in data
    assert "total_cost_usd" in data
    assert "top_models" in data
    assert "agents" in data
    assert "error_types" in data


@pytest.mark.anyio
async def test_analytics_custom_hours(client):
    res = await client.get("/api/v1/analytics?hours=1")
    assert res.status_code == 200
    assert res.json()["period_hours"] == 1


# ─── Alerts API Tests ───────────────────────────────────────

@pytest.mark.anyio
async def test_create_alert(client):
    res = await client.post("/api/v1/alerts", json={
        "name": "Test Error Alert",
        "condition_type": "error_rate",
        "threshold": 10.0,
        "webhook_url": "https://httpbin.org/post",
        "window_minutes": 5,
    })
    assert res.status_code == 200
    data = res.json()
    assert "id" in data
    assert data["name"] == "Test Error Alert"


@pytest.mark.anyio
async def test_list_alerts(client):
    res = await client.get("/api/v1/alerts")
    assert res.status_code == 200
    data = res.json()
    assert "rules" in data
    assert isinstance(data["rules"], list)
    assert len(data["rules"]) >= 1


@pytest.mark.anyio
async def test_delete_alert(client):
    # Create one first
    create_res = await client.post("/api/v1/alerts", json={
        "name": "To Delete",
        "condition_type": "cost",
        "threshold": 100.0,
        "webhook_url": "https://httpbin.org/post",
    })
    rule_id = create_res.json()["id"]

    res = await client.delete(f"/api/v1/alerts/{rule_id}")
    assert res.status_code == 200
    assert res.json()["ok"] is True


# ─── Admin API Tests ────────────────────────────────────────

@pytest.mark.anyio
async def test_admin_stats(client):
    res = await client.get("/api/v1/admin/stats")
    assert res.status_code == 200
    data = res.json()
    assert "event_count" in data
    assert "session_count" in data
    assert "db_size_bytes" in data


# ─── Live Feed Tests ────────────────────────────────────────

@pytest.mark.anyio
async def test_live_poll(client):
    res = await client.get("/api/v1/live")
    assert res.status_code == 200
    data = res.json()
    assert "events" in data


# ─── Rate Limiting Tests ────────────────────────────────────

@pytest.mark.anyio
async def test_rate_limit_not_hit_on_normal_usage(client):
    """Normal usage should not hit rate limits."""
    for _ in range(5):
        res = await client.get("/api/health")
        assert res.status_code == 200


# ─── RBAC Tests ─────────────────────────────────────────────

@pytest.mark.anyio
async def test_key_management(client):
    """Test API key CRUD."""
    # Create a key
    res = await client.post("/api/v1/keys", json={
        "name": "Test Key",
        "role": "member",
    })
    assert res.status_code == 200
    data = res.json()
    assert "key" in data
    assert data["role"] == "member"
    key = data["key"]

    # List keys
    res = await client.get("/api/v1/keys")
    assert res.status_code == 200
    keys = res.json()["keys"]
    assert any(k["name"] == "Test Key" for k in keys)

    # Revoke key
    key_id = data["id"]
    res = await client.delete(f"/api/v1/keys/{key_id}")
    assert res.status_code == 200
    assert res.json()["ok"] is True


@pytest.mark.anyio
async def test_viewer_cannot_ingest(client):
    """Viewer role should not be able to ingest events."""
    # Create a viewer key
    res = await client.post("/api/v1/keys", json={
        "name": "Viewer Key",
        "role": "viewer",
    })
    viewer_key = res.json()["key"]

    # Try to ingest — should fail with 403
    res = await client.post(
        "/api/v1/events",
        json={"events": [{"event_type": "llm.response", "timestamp": time.time()}]},
        headers={"Authorization": f"Bearer {viewer_key}"},
    )
    assert res.status_code == 403


@pytest.mark.anyio
async def test_member_can_read(client):
    """Member role should be able to read sessions."""
    # Create a member key
    res = await client.post("/api/v1/keys", json={
        "name": "Member Key",
        "role": "member",
    })
    member_key = res.json()["key"]

    # Read sessions — should work
    res = await client.get(
        "/api/v1/sessions",
        headers={"Authorization": f"Bearer {member_key}"},
    )
    assert res.status_code == 200


@pytest.mark.anyio
async def test_member_cannot_manage_keys(client):
    """Member role should not be able to create API keys."""
    # Create a member key
    res = await client.post("/api/v1/keys", json={
        "name": "Member Key 2",
        "role": "member",
    })
    member_key = res.json()["key"]

    # Try to create another key — should fail with 403
    res = await client.post(
        "/api/v1/keys",
        json={"name": "Should Fail", "role": "viewer"},
        headers={"Authorization": f"Bearer {member_key}"},
    )
    assert res.status_code == 403


@pytest.mark.anyio
async def test_invalid_api_key(client):
    """Invalid API key should return 401."""
    os.environ["AGENTLENS_REQUIRE_AUTH"] = "true"
    res = await client.get(
        "/api/v1/sessions",
        headers={"Authorization": "Bearer invalid_key_xxxxx"},
    )
    assert res.status_code == 401
    os.environ.pop("AGENTLENS_REQUIRE_AUTH", None)


# ─── Project Management Tests ───────────────────────────────

@pytest.mark.anyio
async def test_create_project(client):
    res = await client.post("/api/v1/projects", json={
        "name": "Test Project",
    })
    assert res.status_code == 200
    data = res.json()
    assert data["id"] == "test-project"
    assert "admin_key" in data  # Auto-created admin key


@pytest.mark.anyio
async def test_list_projects(client):
    res = await client.get("/api/v1/projects")
    assert res.status_code == 200
    projects = res.json()["projects"]
    assert any(p["id"] == "default" for p in projects)


@pytest.mark.anyio
async def test_cannot_delete_default_project(client):
    res = await client.delete("/api/v1/projects/default")
    assert res.status_code == 400


# ─── Audit Log Tests ────────────────────────────────────────

@pytest.mark.anyio
async def test_audit_log(client):
    res = await client.get("/api/v1/audit")
    assert res.status_code == 200
    data = res.json()
    assert "entries" in data
    assert isinstance(data["entries"], list)


# ─── Key Rotation Tests ─────────────────────────────────────

@pytest.mark.anyio
async def test_key_rotation(client):
    """Test creating a key and rotating it."""
    # Create a key
    res = await client.post("/api/v1/keys", json={
        "name": "Rotation Test Key",
        "role": "member",
    })
    assert res.status_code == 200
    key_id = res.json()["id"]
    old_key = res.json()["key"]

    # Rotate it
    res = await client.post(f"/api/v1/keys/{key_id}/rotate", json={
        "grace_period_hours": 48,
    })
    assert res.status_code == 200
    data = res.json()
    assert "new_key" in data
    assert data["old_key_id"] == key_id
    assert data["grace_period_hours"] == 48
    new_key = data["new_key"]["key"]
    assert new_key != old_key


@pytest.mark.anyio
async def test_rotate_nonexistent_key(client):
    """Rotating a nonexistent key should return 404."""
    res = await client.post("/api/v1/keys/nonexistent-id/rotate", json={
        "grace_period_hours": 24,
    })
    assert res.status_code == 404


# ─── Data Retention Tests ───────────────────────────────────

@pytest.mark.anyio
async def test_set_retention_policy(client):
    """Test setting a data retention policy."""
    res = await client.put("/api/v1/retention", json={
        "retention_days": 60,
        "delete_events": True,
        "delete_sessions": True,
        "delete_audit_logs": False,
    })
    assert res.status_code == 200
    data = res.json()
    assert data["retention_days"] == 60
    assert data["project_id"] == "default"


@pytest.mark.anyio
async def test_get_retention_policy(client):
    """Test getting the retention policy."""
    res = await client.get("/api/v1/retention")
    assert res.status_code == 200
    policy = res.json()["policy"]
    assert policy["retention_days"] == 60


@pytest.mark.anyio
async def test_trigger_retention_purge(client):
    """Test manually triggering a retention purge."""
    res = await client.post("/api/v1/retention/purge")
    assert res.status_code == 200
    data = res.json()
    assert "events_deleted" in data
    assert "sessions_deleted" in data
    assert data["project_id"] == "default"


@pytest.mark.anyio
async def test_retention_history(client):
    """Test getting purge history."""
    res = await client.get("/api/v1/retention/history")
    assert res.status_code == 200
    assert "history" in res.json()


# ─── Encryption Status Tests ────────────────────────────────

@pytest.mark.anyio
async def test_encryption_status(client):
    """Test encryption status endpoint."""
    res = await client.get("/api/v1/admin/encryption")
    assert res.status_code == 200
    data = res.json()
    assert "encryption_at_rest" in data
    assert data["rbac_enabled"] is True
    assert data["audit_logging"] is True
    assert data["security_headers"] is True
    if data["encryption_at_rest"]:
        assert len(data["encrypted_fields"]) > 0
        assert "prompt" in data["encrypted_fields"]


# ─── Security Headers Tests ─────────────────────────────────

@pytest.mark.anyio
async def test_security_headers(client):
    """Verify security headers are present on responses."""
    res = await client.get("/api/health")
    assert res.status_code == 200
    assert res.headers.get("X-Content-Type-Options") == "nosniff"
    assert res.headers.get("X-Frame-Options") == "DENY"
    assert res.headers.get("X-XSS-Protection") == "1; mode=block"
    assert res.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
    assert res.headers.get("Cache-Control") == "no-store, no-cache, must-revalidate"


# ─── Health Check Security Info ──────────────────────────────

@pytest.mark.anyio
async def test_health_shows_security(client):
    """Health endpoint should show security posture."""
    res = await client.get("/api/health")
    data = res.json()
    assert "security" in data
    assert data["security"]["rbac"] is True


# ─── OTEL Ingestion Tests ───────────────────────────────────

@pytest.mark.anyio
async def test_otel_empty_payload(client):
    """OTEL endpoint should accept empty payloads."""
    res = await client.post("/v1/traces", json={"resourceSpans": []})
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert data["inserted"] == 0


@pytest.mark.anyio
async def test_otel_with_spans(client):
    """OTEL endpoint should parse and store spans."""
    payload = {
        "resourceSpans": [{
            "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "test-service"}}]},
            "scopeSpans": [{
                "spans": [{
                    "traceId": "abc123",
                    "spanId": "span001",
                    "name": "chat gpt-4o",
                    "startTimeUnixNano": str(int(time.time() * 1e9)),
                    "endTimeUnixNano": str(int((time.time() + 0.5) * 1e9)),
                    "attributes": [
                        {"key": "gen_ai.system", "value": {"stringValue": "openai"}},
                        {"key": "gen_ai.request.model", "value": {"stringValue": "gpt-4o"}},
                    ],
                }]
            }]
        }]
    }
    res = await client.post("/v1/traces", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert data["inserted"] >= 1


@pytest.mark.anyio
async def test_otel_api_v1_path(client):
    """OTEL endpoint should also work at /api/v1/otel/traces."""
    res = await client.post("/api/v1/otel/traces", json={"resourceSpans": []})
    assert res.status_code == 200
    assert res.json()["ok"] is True


# ─── Trace Tree Tests ───────────────────────────────────────

@pytest.mark.anyio
async def test_trace_tree_not_found(client):
    """Should 404 for nonexistent trace."""
    res = await client.get("/api/v1/traces/nonexistent-xyz")
    assert res.status_code == 404


@pytest.mark.anyio
async def test_trace_tree_with_data(client):
    """Should return trace tree for a session with events."""
    session_id = f"trace-test-{uuid.uuid4().hex[:8]}"
    # Insert events with parent relationships
    events = [
        {"event_type": "session.start", "session_id": session_id, "agent_name": "test-agent",
         "timestamp": time.time(), "event_id": f"root-{uuid.uuid4().hex[:8]}"},
        {"event_type": "llm.response", "session_id": session_id, "agent_name": "test-agent",
         "timestamp": time.time() + 0.1, "model": "gpt-4o",
         "event_id": f"llm-{uuid.uuid4().hex[:8]}", "parent_id": f"root-{uuid.uuid4().hex[:8]}"},
    ]
    await client.post("/api/v1/events", json={"events": events})

    res = await client.get(f"/api/v1/traces/{session_id}")
    assert res.status_code == 200
    data = res.json()
    assert data["trace_id"] == session_id
    assert len(data["all_events"]) >= 2
    assert "stats" in data
    assert data["stats"]["total_events"] >= 2


# ─── Prompt Diff Tests ──────────────────────────────────────

@pytest.mark.anyio
async def test_event_detail(client):
    """Should return event detail with similar prompts."""
    eid = f"detail-{uuid.uuid4().hex[:8]}"
    await client.post("/api/v1/events", json={"events": [{
        "event_type": "llm.response", "event_id": eid, "session_id": "diff-test",
        "agent_name": "test-agent", "timestamp": time.time(),
        "model": "gpt-4o", "prompt": "What is the weather?", "completion": "Sunny and warm!",
    }]})

    res = await client.get(f"/api/v1/events/{eid}/detail")
    assert res.status_code == 200
    data = res.json()
    assert "event" in data
    assert "similar_prompts" in data


@pytest.mark.anyio
async def test_diff_events(client):
    """Should compute diff between two events."""
    eid_a = f"diffA-{uuid.uuid4().hex[:8]}"
    eid_b = f"diffB-{uuid.uuid4().hex[:8]}"
    await client.post("/api/v1/events", json={"events": [
        {"event_type": "llm.response", "event_id": eid_a, "session_id": "diff-test",
         "agent_name": "test-agent", "timestamp": time.time(),
         "prompt": "What is the weather in NYC?", "completion": "Sunny!"},
        {"event_type": "llm.response", "event_id": eid_b, "session_id": "diff-test",
         "agent_name": "test-agent", "timestamp": time.time(),
         "prompt": "What is the weather in LA?", "completion": "Also sunny!"},
    ]})

    res = await client.get(f"/api/v1/events/{eid_a}/diff/{eid_b}")
    assert res.status_code == 200
    data = res.json()
    assert "prompt_similarity" in data
    assert "prompt_diff" in data
    assert data["prompt_similarity"] > 0  # Should be somewhat similar


# ─── Cost Anomaly Tests ─────────────────────────────────────

@pytest.mark.anyio
async def test_get_anomalies(client):
    """Should return anomaly list (possibly empty)."""
    res = await client.get("/api/v1/anomalies")
    assert res.status_code == 200
    data = res.json()
    assert "anomalies" in data
    assert isinstance(data["anomalies"], list)


@pytest.mark.anyio
async def test_get_cost_trends(client):
    """Should return cost trends."""
    res = await client.get("/api/v1/anomalies/trends?days=7")
    assert res.status_code == 200
    data = res.json()
    assert "trends" in data


@pytest.mark.anyio
async def test_trigger_anomaly_detection(client):
    """Should allow manual anomaly detection trigger."""
    res = await client.post("/api/v1/anomalies/detect")
    assert res.status_code == 200
    data = res.json()
    assert "anomalies_detected" in data


# ─── Demo Data Tests ────────────────────────────────────────

@pytest.mark.anyio
async def test_load_demo_data(client):
    """Should load demo data and return count."""
    res = await client.post("/api/v1/demo/load")
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert data["inserted"] > 0
    assert "agents" in data
    assert len(data["agents"]) >= 5


# ─── Session Graph Tests ────────────────────────────────────

@pytest.mark.anyio
async def test_session_graph_not_found(client):
    """Should 404 for nonexistent session graph."""
    res = await client.get("/api/v1/sessions/nonexistent-graph/graph")
    assert res.status_code == 404


@pytest.mark.anyio
async def test_session_graph_with_data(client):
    """Should return graph for a session with events (proper tree structure)."""
    session_id = f"graph-test-{uuid.uuid4().hex[:8]}"
    start_id = f"g1-{uuid.uuid4().hex[:8]}"
    step_id = f"g2-{uuid.uuid4().hex[:8]}"
    events = [
        {"event_type": "session.start", "session_id": session_id, "agent_name": "graph-agent",
         "timestamp": time.time(), "event_id": start_id},
        {"event_type": "agent.step", "session_id": session_id, "agent_name": "graph-agent",
         "timestamp": time.time() + 0.05, "event_id": step_id,
         "parent_id": start_id, "step_number": 1, "decision": "search"},
        {"event_type": "llm.response", "session_id": session_id, "agent_name": "graph-agent",
         "timestamp": time.time() + 0.1, "event_id": f"g3-{uuid.uuid4().hex[:8]}",
         "parent_id": step_id, "model": "gpt-4"},
        {"event_type": "tool.call", "session_id": session_id, "agent_name": "graph-agent",
         "timestamp": time.time() + 0.2, "event_id": f"g4-{uuid.uuid4().hex[:8]}",
         "parent_id": step_id, "tool_name": "search"},
        {"event_type": "session.end", "session_id": session_id, "agent_name": "graph-agent",
         "timestamp": time.time() + 0.3, "event_id": f"g5-{uuid.uuid4().hex[:8]}",
         "success": True},
    ]
    await client.post("/api/v1/events", json={"events": events})

    res = await client.get(f"/api/v1/sessions/{session_id}/graph")
    assert res.status_code == 200
    data = res.json()
    assert "nodes" in data
    assert "edges" in data
    # spine: session.start + step + session.end = 3, leaves: llm + tool = 2
    assert len(data["nodes"]) >= 5
    # flow edges: start→step, step→end = 2, child edges: step→llm, step→tool = 2
    assert len(data["edges"]) >= 4
    assert data["stats"]["unique_agents"] >= 1
    # Verify roles exist
    roles = {n["role"] for n in data["nodes"]}
    assert "spine" in roles
    assert "leaf" in roles


# ─── User Filtering Tests ───────────────────────────────────

@pytest.mark.anyio
async def test_ingest_events_with_user_id(client):
    """Should accept events with user_id field."""
    session_id = f"user-test-{uuid.uuid4().hex[:8]}"
    events = [
        {"event_type": "session.start", "session_id": session_id, "agent_name": "user-agent",
         "timestamp": time.time(), "event_id": f"u1-{uuid.uuid4().hex[:8]}", "user_id": "user_42"},
        {"event_type": "llm.response", "session_id": session_id, "agent_name": "user-agent",
         "timestamp": time.time() + 0.1, "event_id": f"u2-{uuid.uuid4().hex[:8]}", "user_id": "user_42",
         "model": "gpt-4", "prompt": "hi", "completion": "hello"},
    ]
    res = await client.post("/api/v1/events", json={"events": events})
    assert res.status_code == 200
    assert res.json()["ok"] is True


@pytest.mark.anyio
async def test_list_sessions_filter_by_user(client):
    """Should filter sessions by user_id."""
    res = await client.get("/api/v1/sessions?user=user_42")
    assert res.status_code == 200
    data = res.json()
    assert "sessions" in data
    # All returned sessions should have user_id == user_42
    for s in data["sessions"]:
        assert s.get("user_id") == "user_42"


@pytest.mark.anyio
async def test_list_sessions_filter_by_nonexistent_user(client):
    """Should return empty for nonexistent user."""
    res = await client.get("/api/v1/sessions?user=nobody_here_999")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 0
    assert len(data["sessions"]) == 0


# ─── Prometheus Metrics Tests ────────────────────────────────

@pytest.mark.anyio
async def test_metrics_endpoint_exists(client):
    """Should expose Prometheus /metrics."""
    res = await client.get("/metrics")
    assert res.status_code == 200
    body = res.text
    assert "agentlens_events_total" in body
    assert "agentlens_sessions_total" in body
    assert "agentlens_errors_total" in body
    assert "agentlens_cost_usd_total" in body
    assert "agentlens_uptime_seconds" in body


@pytest.mark.anyio
async def test_metrics_has_histogram(client):
    """Should include LLM latency histogram."""
    res = await client.get("/metrics")
    assert res.status_code == 200
    body = res.text
    assert "agentlens_llm_latency_seconds_bucket" in body
    assert "agentlens_llm_latency_seconds_sum" in body
    assert "agentlens_llm_latency_seconds_count" in body


@pytest.mark.anyio
async def test_metrics_format(client):
    """Metrics should follow Prometheus text exposition format."""
    res = await client.get("/metrics")
    assert res.status_code == 200
    assert "text/plain" in res.headers.get("content-type", "")
    lines = res.text.strip().split("\n")
    # Should have at least HELP and TYPE lines
    help_lines = [l for l in lines if l.startswith("# HELP")]
    type_lines = [l for l in lines if l.startswith("# TYPE")]
    assert len(help_lines) >= 5
    assert len(type_lines) >= 5
