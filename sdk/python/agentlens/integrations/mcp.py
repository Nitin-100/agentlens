"""
AgentLens MCP (Model Context Protocol) Integration — Production Grade.

Provides an MCP Server that exposes AgentLens observability data as MCP resources
and tools, allowing any MCP-compatible client (Claude Desktop, Cursor, etc.)
to query agent sessions, analytics, errors, and live events.

Also provides an MCP Client interceptor that auto-captures all MCP tool calls
made by agents using MCP-based tool servers.

Architecture:
    ┌──────────────┐     MCP Protocol      ┌──────────────────┐
    │ Claude / IDE  │ ◄──────────────────► │  AgentLens MCP   │
    │  (MCP Client) │     Resources+Tools   │    Server        │
    └──────────────┘                        └──────┬───────────┘
                                                   │ HTTP
                                                   ▼
                                            ┌──────────────┐
                                            │  AgentLens   │
                                            │   Backend    │
                                            └──────────────┘

Usage (MCP Server — expose data to Claude/IDE):
    agentlens-mcp serve --port 8341 --backend http://localhost:8340

Usage (MCP Client interceptor — capture agent MCP tool calls):
    from agentlens.integrations.mcp import patch_mcp_client
    patch_mcp_client()
"""

import json
import time
import asyncio
import logging
from typing import Optional, Any, Dict, List, TYPE_CHECKING

if TYPE_CHECKING:
    from ..client import AgentLens

logger = logging.getLogger("agentlens.mcp")


# ──────────────────────────────────────────────────────────────
# Part 1: MCP Client Interceptor
# Captures all MCP tool calls made by agents
# ──────────────────────────────────────────────────────────────

def patch_mcp_client(lens: Optional["AgentLens"] = None):
    """Patch the MCP Python client to auto-capture all tool calls.

    Works with the official `mcp` package (pip install mcp).
    Intercepts ClientSession.call_tool() to record every MCP tool invocation.
    """
    try:
        from mcp import ClientSession
    except ImportError:
        raise ImportError("mcp package not installed. Run: pip install mcp")

    if lens is None:
        from ..client import AgentLens
        lens = AgentLens.get_instance()
        if not lens:
            raise ValueError("No AgentLens instance found.")

    import functools

    # Patch call_tool
    original_call_tool = ClientSession.call_tool

    @functools.wraps(original_call_tool)
    async def patched_call_tool(self, name: str, arguments: dict = None, **kwargs):
        start = time.time()

        try:
            result = await original_call_tool(self, name, arguments, **kwargs)
            elapsed = (time.time() - start) * 1000

            # Extract result content
            result_text = ""
            if hasattr(result, "content"):
                for block in result.content:
                    if hasattr(block, "text"):
                        result_text += block.text

            is_error = getattr(result, "isError", False)

            lens.record_tool_call(
                tool_name=f"mcp:{name}",
                args=arguments or {},
                result=result_text[:1000] if result_text else None,
                duration_ms=elapsed,
                success=not is_error,
                error=result_text[:500] if is_error else None,
                tags={"protocol": "mcp", "transport": "stdio/sse"},
            )

            return result

        except Exception as e:
            elapsed = (time.time() - start) * 1000
            lens.record_tool_call(
                tool_name=f"mcp:{name}",
                args=arguments or {},
                duration_ms=elapsed,
                success=False,
                error=str(e),
                tags={"protocol": "mcp"},
            )
            lens.record_error(e, context=f"MCP tool '{name}' failed")
            raise

    ClientSession.call_tool = patched_call_tool

    # Patch list_tools to track tool discovery
    if hasattr(ClientSession, "list_tools"):
        original_list_tools = ClientSession.list_tools

        @functools.wraps(original_list_tools)
        async def patched_list_tools(self, **kwargs):
            start = time.time()
            try:
                result = await original_list_tools(self, **kwargs)
                elapsed = (time.time() - start) * 1000

                tool_names = []
                if hasattr(result, "tools"):
                    tool_names = [t.name for t in result.tools]

                lens.record_custom(
                    "mcp:list_tools",
                    data={"tools": tool_names, "count": len(tool_names), "latency_ms": elapsed},
                    tags={"protocol": "mcp"},
                )
                return result
            except Exception as e:
                lens.record_error(e, context="MCP list_tools failed")
                raise

        ClientSession.list_tools = patched_list_tools

    # Patch read_resource
    if hasattr(ClientSession, "read_resource"):
        original_read_resource = ClientSession.read_resource

        @functools.wraps(original_read_resource)
        async def patched_read_resource(self, uri: str, **kwargs):
            start = time.time()
            try:
                result = await original_read_resource(self, uri, **kwargs)
                elapsed = (time.time() - start) * 1000

                lens.record_custom(
                    "mcp:read_resource",
                    data={"uri": uri, "latency_ms": elapsed},
                    tags={"protocol": "mcp"},
                )
                return result
            except Exception as e:
                lens.record_error(e, context=f"MCP read_resource '{uri}' failed")
                raise

        ClientSession.read_resource = patched_read_resource

    if lens.verbose:
        print("[AgentLens] MCP client patched — all tool calls, list_tools, read_resource tracked")


# ──────────────────────────────────────────────────────────────
# Part 2: MCP Server — Expose AgentLens data via MCP protocol
# ──────────────────────────────────────────────────────────────

class AgentLensMCPServer:
    """
    MCP Server that exposes AgentLens observability data as MCP resources and tools.

    Resources:
        agentlens://sessions         — List recent sessions
        agentlens://sessions/{id}    — Session detail with events
        agentlens://analytics        — Overview analytics
        agentlens://errors           — Recent errors
        agentlens://health           — System health

    Tools:
        query_sessions   — Search/filter sessions
        query_analytics  — Get analytics for a time window
        query_errors     — Get errors with filtering
        create_alert     — Create an alert rule
        run_cleanup      — Run data retention cleanup
    """

    def __init__(self, backend_url: str = "http://localhost:8340", api_key: str = ""):
        self.backend_url = backend_url.rstrip("/")
        self.api_key = api_key

    def _fetch(self, endpoint: str, method: str = "GET", data: dict = None) -> dict:
        """HTTP call to AgentLens backend."""
        from urllib.request import Request, urlopen
        from urllib.error import URLError
        import json

        url = f"{self.backend_url}{endpoint}"
        body = json.dumps(data).encode() if data else None
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        req = Request(url, data=body, headers=headers, method=method)
        try:
            with urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode())
        except Exception as e:
            return {"error": str(e)}

    # ─── Resources ───────────────────────────────────────────

    def list_resources(self) -> list:
        return [
            {"uri": "agentlens://sessions", "name": "Agent Sessions", "mimeType": "application/json",
             "description": "List of recent agent execution sessions"},
            {"uri": "agentlens://analytics", "name": "Analytics Overview", "mimeType": "application/json",
             "description": "Aggregated analytics — costs, tokens, errors, top agents/models"},
            {"uri": "agentlens://errors", "name": "Recent Errors", "mimeType": "application/json",
             "description": "Recent agent errors with stack traces"},
            {"uri": "agentlens://health", "name": "System Health", "mimeType": "application/json",
             "description": "AgentLens server health and database stats"},
        ]

    def read_resource(self, uri: str) -> dict:
        if uri == "agentlens://sessions":
            return self._fetch("/api/v1/sessions?limit=20")
        elif uri.startswith("agentlens://sessions/"):
            session_id = uri.split("/")[-1]
            return self._fetch(f"/api/v1/sessions/{session_id}")
        elif uri == "agentlens://analytics":
            return self._fetch("/api/v1/analytics?hours=24")
        elif uri == "agentlens://errors":
            return self._fetch("/api/v1/events?event_type=error&limit=50")
        elif uri == "agentlens://health":
            return self._fetch("/api/health")
        else:
            return {"error": f"Unknown resource: {uri}"}

    # ─── Tools ───────────────────────────────────────────────

    def list_tools(self) -> list:
        return [
            {
                "name": "query_sessions",
                "description": "Search and filter agent sessions. Returns session list with agent name, cost, tokens, errors, duration.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "agent": {"type": "string", "description": "Filter by agent name"},
                        "limit": {"type": "integer", "description": "Max results (default 20)", "default": 20},
                        "hours": {"type": "integer", "description": "Look back N hours (default 24)", "default": 24},
                    },
                },
            },
            {
                "name": "query_analytics",
                "description": "Get aggregated analytics: total sessions, cost, tokens, error rate, top agents, top models, top tools.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "hours": {"type": "integer", "description": "Time window in hours", "default": 24},
                    },
                },
            },
            {
                "name": "get_session_detail",
                "description": "Get full detail of a specific session including all events timeline (LLM calls, tool calls, errors, steps).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "session_id": {"type": "string", "description": "The session UUID"},
                    },
                    "required": ["session_id"],
                },
            },
            {
                "name": "query_errors",
                "description": "Get recent errors across all agents. Includes error type, message, stack trace, and which agent/session caused it.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "description": "Max errors to return", "default": 20},
                        "agent": {"type": "string", "description": "Filter by agent name"},
                    },
                },
            },
            {
                "name": "create_alert_rule",
                "description": "Create an alert rule to get notified (via webhook) when error rate, cost, or latency exceeds a threshold.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Rule name"},
                        "condition_type": {"type": "string", "enum": ["error_rate", "cost_threshold", "latency_p95", "consecutive_errors"]},
                        "threshold": {"type": "number", "description": "Threshold value"},
                        "webhook_url": {"type": "string", "description": "Webhook URL for notifications"},
                    },
                    "required": ["name", "condition_type", "threshold"],
                },
            },
            {
                "name": "get_system_health",
                "description": "Check AgentLens system health: database status, event/session counts, disk usage.",
                "inputSchema": {"type": "object", "properties": {}},
            },
        ]

    def call_tool(self, name: str, arguments: dict) -> dict:
        if name == "query_sessions":
            params = f"limit={arguments.get('limit', 20)}"
            if arguments.get("agent"):
                params += f"&agent={arguments['agent']}"
            return self._fetch(f"/api/v1/sessions?{params}")

        elif name == "query_analytics":
            hours = arguments.get("hours", 24)
            return self._fetch(f"/api/v1/analytics?hours={hours}")

        elif name == "get_session_detail":
            sid = arguments["session_id"]
            return self._fetch(f"/api/v1/sessions/{sid}")

        elif name == "query_errors":
            limit = arguments.get("limit", 20)
            return self._fetch(f"/api/v1/events?event_type=error&limit={limit}")

        elif name == "create_alert_rule":
            return self._fetch("/api/v1/alerts", method="POST", data=arguments)

        elif name == "get_system_health":
            return self._fetch("/api/health")

        else:
            return {"error": f"Unknown tool: {name}"}

    # ─── Run as MCP Server ───────────────────────────────────

    async def serve_stdio(self):
        """Run as MCP server over stdio (for Claude Desktop, Cursor, etc.)."""
        try:
            from mcp.server import Server
            from mcp.server.stdio import stdio_server
            from mcp import types
        except ImportError:
            raise ImportError(
                "mcp[server] not installed. Run: pip install 'mcp[cli]'"
            )

        server = Server("agentlens")

        @server.list_resources()
        async def handle_list_resources():
            resources = self.list_resources()
            return [
                types.Resource(
                    uri=r["uri"],
                    name=r["name"],
                    description=r.get("description", ""),
                    mimeType=r.get("mimeType", "application/json"),
                )
                for r in resources
            ]

        @server.read_resource()
        async def handle_read_resource(uri: str):
            data = await asyncio.get_event_loop().run_in_executor(
                None, self.read_resource, str(uri)
            )
            return json.dumps(data, indent=2, default=str)

        @server.list_tools()
        async def handle_list_tools():
            tools = self.list_tools()
            return [
                types.Tool(
                    name=t["name"],
                    description=t["description"],
                    inputSchema=t["inputSchema"],
                )
                for t in tools
            ]

        @server.call_tool()
        async def handle_call_tool(name: str, arguments: dict):
            data = await asyncio.get_event_loop().run_in_executor(
                None, self.call_tool, name, arguments
            )
            return [types.TextContent(type="text", text=json.dumps(data, indent=2, default=str))]

        logger.info("Starting AgentLens MCP server (stdio)...")
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())

    async def serve_sse(self, host: str = "0.0.0.0", port: int = 8341):
        """Run as MCP server over SSE (for web-based MCP clients)."""
        try:
            from mcp.server import Server
            from mcp.server.sse import SseServerTransport
            from mcp import types
            from starlette.applications import Starlette
            from starlette.routing import Route, Mount
            import uvicorn
        except ImportError:
            raise ImportError(
                "mcp[server] and starlette not installed. Run: pip install 'mcp[cli]' starlette uvicorn"
            )

        server = Server("agentlens")
        sse = SseServerTransport("/messages/")

        @server.list_resources()
        async def handle_list_resources():
            resources = self.list_resources()
            return [
                types.Resource(
                    uri=r["uri"], name=r["name"],
                    description=r.get("description", ""),
                    mimeType=r.get("mimeType", "application/json"),
                )
                for r in resources
            ]

        @server.read_resource()
        async def handle_read_resource(uri: str):
            data = await asyncio.get_event_loop().run_in_executor(
                None, self.read_resource, str(uri)
            )
            return json.dumps(data, indent=2, default=str)

        @server.list_tools()
        async def handle_list_tools():
            tools = self.list_tools()
            return [
                types.Tool(
                    name=t["name"], description=t["description"],
                    inputSchema=t["inputSchema"],
                )
                for t in tools
            ]

        @server.call_tool()
        async def handle_call_tool(name: str, arguments: dict):
            data = await asyncio.get_event_loop().run_in_executor(
                None, self.call_tool, name, arguments
            )
            return [types.TextContent(type="text", text=json.dumps(data, indent=2, default=str))]

        async def handle_sse(request):
            async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
                await server.run(streams[0], streams[1], server.create_initialization_options())

        app = Starlette(routes=[
            Route("/sse", endpoint=handle_sse),
            Mount("/messages/", app=sse.handle_post_message),
        ])

        logger.info(f"Starting AgentLens MCP server (SSE) on {host}:{port}")
        config = uvicorn.Config(app, host=host, port=port, log_level="info")
        server_instance = uvicorn.Server(config)
        await server_instance.serve()


def create_mcp_config(backend_url: str = "http://localhost:8340") -> dict:
    """Generate MCP config for Claude Desktop / Cursor / etc.

    Returns the JSON config block to add to your MCP settings file.
    """
    return {
        "mcpServers": {
            "agentlens": {
                "command": "python",
                "args": ["-m", "agentlens.integrations.mcp", "serve", "--backend", backend_url],
                "env": {}
            }
        }
    }


# ─── CLI entry point ────────────────────────────────────────

def main():
    """CLI entry point for running the MCP server."""
    import argparse

    parser = argparse.ArgumentParser(description="AgentLens MCP Server")
    parser.add_argument("command", choices=["serve", "config"], help="Command to run")
    parser.add_argument("--backend", default="http://localhost:8340", help="AgentLens backend URL")
    parser.add_argument("--transport", choices=["stdio", "sse"], default="stdio", help="MCP transport")
    parser.add_argument("--port", type=int, default=8341, help="Port for SSE transport")
    parser.add_argument("--api-key", default="", help="API key for backend auth")

    args = parser.parse_args()

    if args.command == "config":
        config = create_mcp_config(args.backend)
        print(json.dumps(config, indent=2))
        return

    server = AgentLensMCPServer(backend_url=args.backend, api_key=args.api_key)

    if args.transport == "stdio":
        asyncio.run(server.serve_stdio())
    else:
        asyncio.run(server.serve_sse(port=args.port))


if __name__ == "__main__":
    main()
