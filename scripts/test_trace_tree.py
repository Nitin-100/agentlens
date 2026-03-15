"""Test the trace tree API to verify hierarchical structure."""
import requests
import json

HEADERS = {"Authorization": "Bearer al_default_key"}
BASE = "http://localhost:8340/api/v1"

# Get sessions
r = requests.get(f"{BASE}/sessions", headers=HEADERS)
sessions = r.json()["sessions"]
sid = sessions[0]["id"]
agent = sessions[0]["agent_name"]
print(f"Testing session: {sid} ({agent})")

# Get trace tree
r2 = requests.get(f"{BASE}/traces/{sid}", headers=HEADERS)
tree = r2.json()
print(f"Stats: {json.dumps(tree['stats'], indent=2)}")
print(f"Root spans: {len(tree['root_spans'])}")
print()


def print_tree(node, indent=0):
    t = node.get("event_type", "?")
    d = node.get("duration_ms") or node.get("latency_ms") or 0
    lbl = node.get("tool_name") or node.get("model") or node.get("agent_name") or ""
    cost = node.get("cost_usd", 0) or 0
    kids = len(node.get("children", []))
    bar = "█" * max(int(d / 200), 1) if d > 0 else ""
    info = f"{t:<20} {lbl:<25} {bar:<20} {d:>7.0f}ms"
    if cost > 0:
        info += f"  ${cost:.4f}"
    if kids:
        info += f"  [{kids} children]"
    print("  " * indent + info)
    for c in node.get("children", []):
        print_tree(c, indent + 1)


for root in tree["root_spans"]:
    print_tree(root)

print("\n--- Testing a second session ---")
sid2 = sessions[min(5, len(sessions) - 1)]["id"]
agent2 = sessions[min(5, len(sessions) - 1)]["agent_name"]
print(f"Session: {sid2} ({agent2})\n")
r3 = requests.get(f"{BASE}/traces/{sid2}", headers=HEADERS)
tree2 = r3.json()
for root in tree2["root_spans"]:
    print_tree(root)

# Also test graph
print("\n--- Graph View ---")
r4 = requests.get(f"{BASE}/sessions/{sid}/graph", headers=HEADERS)
graph = r4.json()
print(f"Nodes: {graph['stats']['total_nodes']}, Edges: {graph['stats']['total_edges']}")
for n in graph["nodes"][:5]:
    print(f"  {n['type']:<20} {n['label']:<15} status={n['status']}")
for e in graph["edges"][:5]:
    print(f"  {e['from'][:12]}... -> {e['to'][:12]}... ({e['label']})")
