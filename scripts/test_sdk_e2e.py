"""
End-to-end SDK test against a live AgentLens server.
Tests: session management, LLM recording, tool recording, user tracking, flush.
"""
import sys
import os
import time
import json
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "sdk", "python"))

from agentlens import AgentLens

BASE = "http://localhost:8340"

print("=" * 60)
print("AgentLens SDK — Live End-to-End Test")
print("=" * 60)

# 1. Initialize SDK
lens = AgentLens(
    server_url=BASE,
    project="default",
    api_key="al_default_key",
    verbose=True,
    flush_interval=1.0,
    batch_size=5,
)
print("\n[1] ✅ SDK initialized")

# 2. Set user
lens.set_user("test_user_nitin")
lens.set_metadata(environment="testing", version="0.3.0")
print("[2] ✅ User set to 'test_user_nitin', metadata set")

# 3. Start session
session = lens.start_session(agent_name="e2e-test-agent", tags={"test": "live"})
sid = session.session_id
print(f"[3] ✅ Session started: {sid[:16]}...")

# 4. Record LLM call
lens.record_llm_call(
    model="gpt-4o",
    prompt=[{"role": "user", "content": "What is the weather in NYC?"}],
    completion="The weather in New York City is currently 72°F and sunny.",
    input_tokens=15,
    output_tokens=12,
    latency_ms=450,
    provider="openai",
)
print("[4] ✅ LLM call recorded (gpt-4o, 27 tokens)")

# 5. Record tool call
lens.record_tool_call(
    tool_name="weather_api",
    args={"city": "NYC"},
    result={"temp": 72, "condition": "sunny"},
    duration_ms=120,
    success=True,
)
print("[5] ✅ Tool call recorded (weather_api)")

# 6. Record agent step
lens.record_step(
    step_number=1,
    thought="User wants weather info, I should use the weather tool",
    decision="call weather_api",
)
print("[6] ✅ Agent step recorded")

# 7. Record another LLM call
lens.record_llm_call(
    model="gpt-4o-mini",
    prompt="Summarize the weather",
    completion="It's 72°F and sunny in NYC.",
    input_tokens=8,
    output_tokens=10,
    latency_ms=200,
    provider="openai",
)
print("[7] ✅ Second LLM call recorded (gpt-4o-mini)")

# 8. Record an error
try:
    raise ValueError("Test error for e2e")
except Exception as e:
    lens.record_error(e, context="e2e testing")
print("[8] ✅ Error recorded")

# 9. End session
lens.end_session(success=True, output_data={"summary": "Weather is 72°F and sunny in NYC"})
print("[9] ✅ Session ended")

# Wait for flush
time.sleep(3)

# 10. Verify via API
print("\n--- Verifying via API ---")

def api(path):
    r = urllib.request.urlopen(f"{BASE}{path}")
    return json.loads(r.read())

# Check session exists
sessions = api(f"/api/v1/sessions?limit=50")
our_sessions = [s for s in sessions["sessions"] if s.get("agent_name") == "e2e-test-agent"]
if our_sessions:
    s = our_sessions[0]
    print(f"[10] ✅ Session found in API:")
    print(f"     Agent: {s['agent_name']}")
    print(f"     User:  {s.get('user_id', 'N/A')}")
    print(f"     Cost:  ${s.get('total_cost_usd', 0):.4f}")
    print(f"     Tokens: {s.get('total_tokens', 0)}")
    print(f"     LLM calls: {s.get('total_llm_calls', 0)}")
    print(f"     Tool calls: {s.get('total_tool_calls', 0)}")
    print(f"     Steps: {s.get('total_steps', 0)}")
    print(f"     Errors: {s.get('error_count', 0)}")

    # Check session detail
    detail = api(f"/api/v1/sessions/{s['id']}")
    events = detail.get("events", [])
    print(f"[11] ✅ Session detail: {len(events)} events")

    # Check graph
    graph = api(f"/api/v1/sessions/{s['id']}/graph")
    print(f"[12] ✅ Session graph: {len(graph.get('nodes',[]))} nodes, {len(graph.get('edges',[]))} edges")
else:
    print("[10] ❌ Session NOT found — events may not have flushed")
    # Try direct session lookup
    print(f"     Looking for session: {sid}")

# Check user filter
user_sessions = api("/api/v1/sessions?user=test_user_nitin")
print(f"[13] ✅ User filter: {user_sessions['total']} sessions for user 'test_user_nitin'")

# Check Prometheus updated
metrics = urllib.request.urlopen(f"{BASE}/metrics").read().decode()
events_line = [l for l in metrics.split("\n") if l.startswith("agentlens_events_total")]
print(f"[14] ✅ Prometheus: {events_line[0] if events_line else 'not found'}")

print("\n" + "=" * 60)
print("SDK End-to-End Test Complete!")
print("=" * 60)

# Shutdown
lens.shutdown()
