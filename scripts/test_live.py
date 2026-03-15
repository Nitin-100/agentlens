"""End-to-end API test against live AgentLens server."""
import urllib.request
import json

BASE = "http://localhost:8340"

def api(path):
    r = urllib.request.urlopen(f"{BASE}{path}")
    return json.loads(r.read())

def raw(path):
    r = urllib.request.urlopen(f"{BASE}{path}")
    return r.read().decode()

print("=" * 60)
print("AgentLens — Live API Test")
print("=" * 60)

# 1. Health
h = api("/api/health")
print(f"\n[1] HEALTH: status={h['status']}, version={h['version']}")
print(f"    DB: {h['db']['event_count']} events, {h['db']['session_count']} sessions")

# 2. Sessions
s = api("/api/v1/sessions?limit=5")
print(f"\n[2] SESSIONS: {s['total']} total")
for sess in s["sessions"][:3]:
    sid = sess.get("id", "?")[:12]
    agent = sess.get("agent_name", "?")
    cost = sess.get("total_cost_usd", 0)
    tokens = sess.get("total_tokens", 0)
    user = sess.get("user_id", "-")
    print(f"    {agent:<25} {sid}...  ${cost:.4f}  {tokens} tokens  user={user}")

# 3. Events
e = api("/api/v1/events?limit=5")
events_list = e if isinstance(e, list) else e.get("events", [])
print(f"\n[3] EVENTS: {len(events_list)} returned")
for ev in events_list[:3]:
    print(f"    {ev.get('event_type','?'):<16} {ev.get('agent_name','?'):<20} model={ev.get('model','-')}")

# 4. Analytics
a = api("/api/v1/analytics?hours=24")
print(f"\n[4] ANALYTICS:")
print(f"    Sessions: {a.get('total_sessions',0)}")
print(f"    Events:   {a.get('total_events',0)}")
print(f"    Cost:     ${a.get('total_cost_usd',0):.4f}")
print(f"    Success:  {a.get('success_rate', 0):.1%}")

# 5. Prometheus
body = raw("/metrics")
lines = [l for l in body.split("\n") if l and not l.startswith("#")]
print(f"\n[5] PROMETHEUS METRICS: {len(lines)} metric lines")
for l in lines[:6]:
    print(f"    {l}")

# 6. Trace tree
sessions = s["sessions"]
if sessions:
    sid = sessions[0]["id"]
    try:
        t = api(f"/api/v1/traces/{sid}")
        tree = t.get("tree", t.get("children", []))
        print(f"\n[6] TRACE TREE ({sid[:12]}...): {len(tree)} root nodes")
    except Exception as ex:
        print(f"\n[6] TRACE TREE: {ex}")

# 7. Session graph
if sessions:
    sid = sessions[0]["id"]
    try:
        g = api(f"/api/v1/sessions/{sid}/graph")
        print(f"[7] SESSION GRAPH: {len(g.get('nodes',[]))} nodes, {len(g.get('edges',[]))} edges")
    except Exception as ex:
        print(f"[7] SESSION GRAPH: {ex}")

# 8. Anomalies
try:
    an = api("/api/v1/anomalies")
    print(f"[8] ANOMALIES: {len(an.get('anomalies',[]))} detected")
except Exception as ex:
    print(f"[8] ANOMALIES: {ex}")

# 9. Cost trends
try:
    ct = api("/api/v1/anomalies/trends?days=30")
    print(f"[9] COST TRENDS: {len(ct.get('trends',[]))} data points")
except Exception as ex:
    print(f"[9] COST TRENDS: {ex}")

print("\n" + "=" * 60)
print("All API endpoints tested!")
print("=" * 60)
