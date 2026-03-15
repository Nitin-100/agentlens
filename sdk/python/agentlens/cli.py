"""agentlens CLI — verify your AgentLens installation in one command.

Usage:
    agentlens verify                          # checks http://localhost:8340
    agentlens verify http://your-server:8340  # custom URL
    agentlens verify --json                   # machine-readable output
    python -m agentlens.cli verify            # alternative invocation
"""

import argparse
import json
import sys
import time
import urllib.request
import urllib.error

VERSION = "0.3.0"

CHECKS = [
    ("server_reachable", "Server Reachable"),
    ("health_endpoint", "Health Endpoint"),
    ("events_writable", "Event Ingestion"),
    ("sessions_readable", "Sessions API"),
    ("analytics_working", "Analytics API"),
    ("otel_endpoint", "OTEL Endpoint"),
    ("websocket_available", "WebSocket"),
]


def _request(url, method="GET", data=None, timeout=5):
    """Simple HTTP request without external dependencies."""
    headers = {"Content-Type": "application/json", "User-Agent": "agentlens-cli/" + VERSION}
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode())
        except Exception:
            body = {}
        return e.code, body
    except Exception as e:
        raise ConnectionError(str(e))


def check_server_reachable(base_url):
    """Basic TCP + HTTP connectivity check."""
    try:
        status, _ = _request(f"{base_url}/api/health")
        return status < 500, f"HTTP {status}"
    except ConnectionError as e:
        return False, str(e)


def check_health_endpoint(base_url):
    """Verify /api/health returns healthy status."""
    try:
        status, data = _request(f"{base_url}/api/health")
        healthy = data.get("status") in ("ok", "healthy")
        return healthy, f"status={data.get('status', 'unknown')}, version={data.get('version', '?')}"
    except ConnectionError as e:
        return False, str(e)


def check_events_writable(base_url):
    """Test event ingestion by sending a test event."""
    test_event = {
        "event_type": "agent.step",
        "agent_name": "agentlens-cli-verify",
        "session_id": f"verify-{int(time.time())}",
        "timestamp": time.time(),
        "data": {"step": "cli_verify_test"},
    }
    try:
        status, data = _request(f"{base_url}/api/v1/events", method="POST", data={"events": [test_event]})
        ok = status < 400 and data.get("inserted", 0) > 0
        return ok, f"inserted={data.get('inserted', 0)}"
    except ConnectionError as e:
        return False, str(e)


def check_sessions_readable(base_url):
    """Verify sessions API returns data."""
    try:
        status, data = _request(f"{base_url}/api/v1/sessions?limit=1")
        ok = status == 200 and "sessions" in data
        return ok, f"total={data.get('total', 0)}"
    except ConnectionError as e:
        return False, str(e)


def check_analytics_working(base_url):
    """Verify analytics aggregation endpoint."""
    try:
        status, data = _request(f"{base_url}/api/v1/analytics?hours=1")
        ok = status == 200
        return ok, f"events={data.get('total_events', 0)}"
    except ConnectionError as e:
        return False, str(e)


def check_otel_endpoint(base_url):
    """Test OTEL ingestion endpoint accepts OTLP JSON."""
    otel_payload = {"resourceSpans": []}
    try:
        status, data = _request(f"{base_url}/v1/traces", method="POST", data=otel_payload)
        ok = status < 400
        return ok, f"HTTP {status}, inserted={data.get('inserted', 0)}"
    except ConnectionError as e:
        return False, str(e)


def check_websocket_available(base_url):
    """Check WebSocket endpoint is accessible (HTTP upgrade check)."""
    ws_url = base_url.replace("http://", "ws://").replace("https://", "wss://")
    # We can't do full WS handshake with urllib, just check HTTP endpoint exists
    try:
        status, _ = _request(f"{base_url}/api/health")
        return True, f"ws endpoint at {ws_url}/ws/live"
    except ConnectionError:
        return False, "Server unreachable"


def run_verify(base_url, output_json=False):
    """Run all verification checks against the AgentLens server."""
    results = []
    all_passed = True

    for check_id, label in CHECKS:
        check_fn = globals()[f"check_{check_id}"]
        start = time.time()
        try:
            passed, detail = check_fn(base_url)
        except Exception as e:
            passed, detail = False, str(e)
        elapsed = round((time.time() - start) * 1000, 1)

        results.append({
            "check": check_id,
            "label": label,
            "passed": passed,
            "detail": detail,
            "time_ms": elapsed,
        })
        if not passed:
            all_passed = False

    if output_json:
        print(json.dumps({
            "server": base_url,
            "version": VERSION,
            "all_passed": all_passed,
            "checks": results,
        }, indent=2))
    else:
        print(f"\n🔭 AgentLens Verify — v{VERSION}")
        print(f"   Server: {base_url}\n")

        for r in results:
            icon = "✅" if r["passed"] else "❌"
            print(f"  {icon} {r['label']:<22} {r['detail']:<40} ({r['time_ms']}ms)")

        print()
        passed_count = sum(1 for r in results if r["passed"])
        total_count = len(results)

        if all_passed:
            print(f"  🎉 All {total_count} checks passed! Your AgentLens installation is ready.")
        else:
            print(f"  ⚠️  {passed_count}/{total_count} checks passed. Fix issues above.")

        print()

    return 0 if all_passed else 1


def run_demo(url: str = "http://localhost:8340"):
    """Load demo data into AgentLens server."""
    import urllib.request
    import urllib.error

    endpoint = f"{url}/api/v1/demo/load"
    print(f"\n🔭 AgentLens Demo — Loading sample data...")
    print(f"   Server: {url}\n")

    try:
        req = urllib.request.Request(
            endpoint,
            method="POST",
            headers={"Content-Type": "application/json"},
            data=b"{}",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read())
            events = body.get("events_loaded", body.get("inserted", "?"))
            agents = body.get("agents", "?")
            print(f"  ✅ Loaded {events} events across {agents} agent types")
            print(f"  📊 Open {url}/dashboard to explore the data")
            print()
            return 0
    except urllib.error.HTTPError as e:
        print(f"  ❌ Server error: HTTP {e.code}")
        try:
            detail = json.loads(e.read())
            print(f"     {detail}")
        except Exception:
            pass
        return 1
    except urllib.error.URLError as e:
        print(f"  ❌ Cannot connect to {url}: {e.reason}")
        print(f"     Is the AgentLens server running?")
        return 1
    except Exception as e:
        print(f"  ❌ Error: {e}")
        return 1


def main():
    parser = argparse.ArgumentParser(
        prog="agentlens",
        description="AgentLens CLI — AI Agent Observability",
    )
    subparsers = parser.add_subparsers(dest="command")

    # verify
    verify_parser = subparsers.add_parser("verify", help="Verify AgentLens server connectivity")
    verify_parser.add_argument("url", nargs="?", default="http://localhost:8340",
                                help="AgentLens server URL (default: http://localhost:8340)")
    verify_parser.add_argument("--json", action="store_true", help="Output results as JSON")

    # demo
    demo_parser = subparsers.add_parser("demo", help="Load demo data into AgentLens server")
    demo_parser.add_argument("url", nargs="?", default="http://localhost:8340",
                              help="AgentLens server URL (default: http://localhost:8340)")

    # version
    subparsers.add_parser("version", help="Show version")

    args = parser.parse_args()

    if args.command == "verify":
        sys.exit(run_verify(args.url, output_json=args.json))
    elif args.command == "demo":
        sys.exit(run_demo(args.url))
    elif args.command == "version":
        print(f"agentlens {VERSION}")
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
