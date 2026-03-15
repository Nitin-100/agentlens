#!/bin/bash
# ============================================================
# AgentLens REST API — Universal Examples (cURL)
# 
# Works from ANY language that can make HTTP requests.
# This is the reference for building SDKs in any language.
# ============================================================

SERVER="http://localhost:8340"
API_KEY="al_default_key"

# ─── Health Check ────────────────────────────────────────────

echo "=== Health Check ==="
curl -s "$SERVER/api/health" | python3 -m json.tool

# ─── Start a Session ─────────────────────────────────────────

echo -e "\n=== Ingest Events (Start Session + LLM Call) ==="
curl -s -X POST "$SERVER/api/v1/events" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_KEY" \
  -d '{
    "events": [
      {
        "event_type": "session.start",
        "session_id": "sess_curl_demo_001",
        "agent_name": "curl-agent",
        "timestamp": '$(date +%s.%N)'
      },
      {
        "event_type": "llm.response",
        "session_id": "sess_curl_demo_001",
        "agent_name": "curl-agent",
        "model": "gpt-4o",
        "provider": "openai",
        "prompt": "What is 2+2?",
        "completion": "2+2 equals 4.",
        "input_tokens": 8,
        "output_tokens": 6,
        "total_tokens": 14,
        "cost_usd": 0.00014,
        "latency_ms": 230,
        "timestamp": '$(date +%s.%N)'
      },
      {
        "event_type": "tool.result",
        "session_id": "sess_curl_demo_001",
        "agent_name": "curl-agent",
        "tool_name": "calculator",
        "tool_args": {"expression": "2+2"},
        "tool_result": "4",
        "success": true,
        "duration_ms": 5,
        "timestamp": '$(date +%s.%N)'
      },
      {
        "event_type": "session.end",
        "session_id": "sess_curl_demo_001",
        "agent_name": "curl-agent",
        "success": true,
        "meta": {
          "total_cost": 0.00014,
          "total_tokens": 14,
          "llm_calls": 1,
          "tool_calls": 1,
          "steps": 0,
          "errors": 0
        },
        "timestamp": '$(date +%s.%N)'
      }
    ]
  }' | python3 -m json.tool

# ─── Query Sessions ──────────────────────────────────────────

echo -e "\n=== List Sessions ==="
curl -s "$SERVER/api/v1/sessions?limit=5" \
  -H "Authorization: Bearer $API_KEY" | python3 -m json.tool

# ─── Query Events ────────────────────────────────────────────

echo -e "\n=== List Events ==="
curl -s "$SERVER/api/v1/events?limit=5&event_type=llm.response" \
  -H "Authorization: Bearer $API_KEY" | python3 -m json.tool

# ─── Analytics ───────────────────────────────────────────────

echo -e "\n=== Analytics (last 24h) ==="
curl -s "$SERVER/api/v1/analytics?hours=24" \
  -H "Authorization: Bearer $API_KEY" | python3 -m json.tool

# ─── Create Alert Rule ──────────────────────────────────────

echo -e "\n=== Create Alert Rule ==="
curl -s -X POST "$SERVER/api/v1/alerts" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_KEY" \
  -d '{
    "name": "High Error Rate",
    "condition_type": "error_rate",
    "threshold": 50.0,
    "webhook_url": "https://hooks.slack.com/services/YOUR/WEBHOOK/URL",
    "window_minutes": 5,
    "cooldown_minutes": 15
  }' | python3 -m json.tool

# ─── API Key Management ─────────────────────────────────────

echo -e "\n=== Create API Key ==="
curl -s -X POST "$SERVER/api/v1/keys" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_KEY" \
  -d '{
    "name": "CI Pipeline Key",
    "role": "member",
    "expires_days": 90
  }' | python3 -m json.tool

echo -e "\n=== List API Keys ==="
curl -s "$SERVER/api/v1/keys" \
  -H "Authorization: Bearer $API_KEY" | python3 -m json.tool

# ─── Key Rotation ────────────────────────────────────────────

# Replace KEY_ID with actual key ID from create response
echo -e "\n=== Rotate API Key ==="
curl -s -X POST "$SERVER/api/v1/keys/KEY_ID_HERE/rotate" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_KEY" \
  -d '{"grace_period_hours": 24}' | python3 -m json.tool

# ─── Retention Policy ───────────────────────────────────────

echo -e "\n=== Set Retention Policy (90 days) ==="
curl -s -X PUT "$SERVER/api/v1/retention" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_KEY" \
  -d '{
    "retention_days": 90,
    "delete_events": true,
    "delete_sessions": true,
    "delete_audit_logs": false
  }' | python3 -m json.tool

echo -e "\n=== Get Retention Policy ==="
curl -s "$SERVER/api/v1/retention" \
  -H "Authorization: Bearer $API_KEY" | python3 -m json.tool

echo -e "\n=== Manual Purge ==="
curl -s -X POST "$SERVER/api/v1/retention/purge" \
  -H "Authorization: Bearer $API_KEY" | python3 -m json.tool

# ─── Encryption Status ──────────────────────────────────────

echo -e "\n=== Encryption Status ==="
curl -s "$SERVER/api/v1/admin/encryption" \
  -H "Authorization: Bearer $API_KEY" | python3 -m json.tool

# ─── Audit Log ───────────────────────────────────────────────

echo -e "\n=== Audit Log ==="
curl -s "$SERVER/api/v1/audit?limit=10" \
  -H "Authorization: Bearer $API_KEY" | python3 -m json.tool

# ─── Project Management ─────────────────────────────────────

echo -e "\n=== Create Project ==="
curl -s -X POST "$SERVER/api/v1/projects" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_KEY" \
  -d '{"name": "My Production Agents"}' | python3 -m json.tool

echo -e "\n=== List Projects ==="
curl -s "$SERVER/api/v1/projects" \
  -H "Authorization: Bearer $API_KEY" | python3 -m json.tool

echo ""
echo "============================================================"
echo "  AgentLens REST API — All endpoints demonstrated."
echo "  Any language that can make HTTP POST/GET can use this API."
echo "  Docs: $SERVER/docs (Swagger UI)"
echo "============================================================"
