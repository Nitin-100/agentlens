"""Test graph endpoint output."""
import requests
import json

H = {"Authorization": "Bearer al_default_key"}
BASE = "http://localhost:8340/api/v1"

r = requests.get(f"{BASE}/sessions", headers=H)
ss = r.json()["sessions"]

# Test a few sessions
for idx in [0, 3, 8]:
    if idx >= len(ss):
        break
    sid = ss[idx]["id"]
    agent = ss[idx]["agent_name"]
    print(f"=== Session: {agent} ({sid}) ===")

    r2 = requests.get(f"{BASE}/sessions/{sid}/graph", headers=H)
    g = r2.json()
    print(f"Nodes: {g['stats']['total_nodes']}, Edges: {g['stats']['total_edges']}")

    for n in g["nodes"]:
        dur = f"{n['duration_ms']:.0f}ms" if n.get("duration_ms") else ""
        cost = f"${n['cost_usd']:.4f}" if n.get("cost_usd") else ""
        print(f"  [{n['role']:5}] {n['type']:20} {n['label'][:35]:35} {dur:>8} {cost}")

    print()
    for e in g["edges"]:
        frm = next((n for n in g["nodes"] if n["id"] == e["from"]), None)
        to = next((n for n in g["nodes"] if n["id"] == e["to"]), None)
        fl = frm["label"][:20] if frm else "?"
        tl = to["label"][:20] if to else "?"
        print(f"  {fl:20} --({e['type']:5})--> {tl}")

    print()
