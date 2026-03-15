"""
AgentLens Database — Production-grade async SQLite with connection pooling.

Features:
  - Async DB pool (non-blocking FastAPI)
  - WAL mode for concurrent read/write
  - Proper pagination with total counts
  - Alert rule storage + check conditions
  - Data retention / cleanup
  - DB stats for admin
"""

import os
import json
import time
import sqlite3
import asyncio
import logging
from typing import Optional
from contextlib import asynccontextmanager

logger = logging.getLogger("agentlens.db")

DB_PATH = os.environ.get("AGENTLENS_DB", "agentlens.db")


# ─── Async DB Pool ──────────────────────────────────────────


class AsyncDBPool:
    """Thread-safe async connection pool wrapping sync sqlite3."""

    def __init__(self, db_path: str, pool_size: int = 4):
        self.db_path = db_path
        self.pool_size = pool_size
        self._pool: asyncio.Queue = asyncio.Queue(maxsize=pool_size)
        self._initialized = False

    async def init(self):
        if self._initialized:
            return
        for _ in range(self.pool_size):
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA cache_size=-64000")  # 64MB
            await self._pool.put(conn)
        self._initialized = True
        logger.info(f"DB pool initialized: {self.pool_size} connections")

    @asynccontextmanager
    async def acquire(self):
        conn = await asyncio.wait_for(self._pool.get(), timeout=10.0)
        try:
            yield conn
        finally:
            await self._pool.put(conn)

    async def close(self):
        while not self._pool.empty():
            conn = await self._pool.get()
            conn.close()
        self._initialized = False

    async def fetchall(self, query: str, params: tuple = ()) -> list[dict]:
        async with self.acquire() as conn:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                None, lambda: [dict(r) for r in conn.execute(query, params).fetchall()]
            )

    async def fetchone(self, query: str, params: tuple = ()) -> Optional[dict]:
        async with self.acquire() as conn:
            loop = asyncio.get_event_loop()

            def _do():
                row = conn.execute(query, params).fetchone()
                return dict(row) if row else None
            return await loop.run_in_executor(None, _do)

    async def fetchval(self, query: str, params: tuple = ()):
        async with self.acquire() as conn:
            loop = asyncio.get_event_loop()

            def _do():
                row = conn.execute(query, params).fetchone()
                return row[0] if row else None
            return await loop.run_in_executor(None, _do)

    async def execute_write(self, query: str, params: tuple = ()):
        async with self.acquire() as conn:
            loop = asyncio.get_event_loop()

            def _do():
                conn.execute(query, params)
                conn.commit()
            return await loop.run_in_executor(None, _do)


# Global pool
pool: Optional[AsyncDBPool] = None


async def get_pool() -> AsyncDBPool:
    global pool
    if pool is None:
        pool = AsyncDBPool(DB_PATH)
        await pool.init()
    return pool


# ─── Schema Init ─────────────────────────────────────────────


def init_db():
    """Create tables. Runs SYNC at startup before async loop."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            api_key TEXT UNIQUE NOT NULL,
            created_at REAL NOT NULL,
            settings TEXT DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            agent_name TEXT NOT NULL DEFAULT 'default',
            user_id TEXT,
            started_at REAL NOT NULL,
            ended_at REAL,
            success INTEGER,
            total_cost_usd REAL DEFAULT 0,
            total_tokens INTEGER DEFAULT 0,
            total_llm_calls INTEGER DEFAULT 0,
            total_tool_calls INTEGER DEFAULT 0,
            total_steps INTEGER DEFAULT 0,
            error_count INTEGER DEFAULT 0,
            input_data TEXT,
            output_data TEXT,
            tags TEXT DEFAULT '{}',
            FOREIGN KEY (project_id) REFERENCES projects(id)
        );

        CREATE TABLE IF NOT EXISTS events (
            id TEXT PRIMARY KEY,
            session_id TEXT,
            project_id TEXT NOT NULL,
            agent_name TEXT DEFAULT 'unknown',
            user_id TEXT,
            event_type TEXT NOT NULL,
            timestamp REAL NOT NULL,
            model TEXT,
            provider TEXT,
            prompt TEXT,
            completion TEXT,
            input_tokens INTEGER,
            output_tokens INTEGER,
            total_tokens INTEGER,
            cost_usd REAL,
            latency_ms REAL,
            tool_name TEXT,
            tool_args TEXT,
            tool_result TEXT,
            thought TEXT,
            decision TEXT,
            step_number INTEGER,
            error_message TEXT,
            error_type TEXT,
            stack_trace TEXT,
            success INTEGER,
            duration_ms REAL,
            parent_id TEXT,
            tags TEXT DEFAULT '{}',
            meta TEXT DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS alert_rules (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            name TEXT NOT NULL,
            condition_type TEXT NOT NULL,
            threshold REAL NOT NULL,
            window_minutes INTEGER DEFAULT 5,
            webhook_url TEXT NOT NULL,
            enabled INTEGER DEFAULT 1,
            cooldown_minutes INTEGER DEFAULT 15,
            last_triggered_at REAL DEFAULT 0,
            created_at REAL NOT NULL,
            FOREIGN KEY (project_id) REFERENCES projects(id)
        );

        CREATE TABLE IF NOT EXISTS alert_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rule_id TEXT NOT NULL,
            triggered_at REAL NOT NULL,
            condition_value REAL NOT NULL,
            payload TEXT,
            webhook_status INTEGER,
            FOREIGN KEY (rule_id) REFERENCES alert_rules(id)
        );

        CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id);
        CREATE INDEX IF NOT EXISTS idx_events_project ON events(project_id);
        CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
        CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
        CREATE INDEX IF NOT EXISTS idx_events_project_time ON events(project_id, timestamp);
        CREATE INDEX IF NOT EXISTS idx_sessions_project ON sessions(project_id);
        CREATE INDEX IF NOT EXISTS idx_sessions_agent ON sessions(agent_name);
        CREATE INDEX IF NOT EXISTS idx_sessions_started ON sessions(started_at);
        CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
        CREATE INDEX IF NOT EXISTS idx_events_user ON events(user_id);

        INSERT OR IGNORE INTO projects (id, name, api_key, created_at)
        VALUES ('default', 'Default Project', 'al_default_key', strftime('%s','now'));
    """
    )
    conn.commit()
    conn.close()
    logger.info(f"Database initialized: {DB_PATH}")


# ─── Event Ingestion ─────────────────────────────────────────


async def insert_events(events: list[dict], project_id: str = "default") -> int:
    """Bulk insert events. Async + batched."""
    db = await get_pool()
    inserted = 0

    async with db.acquire() as conn:
        loop = asyncio.get_event_loop()

        def _bulk_insert():
            nonlocal inserted
            for event in events:
                event_id = event.get("event_id", f"evt_{time.time()}_{inserted}")
                session_id = event.get("session_id", "")
                event_type = event.get("event_type", "custom")

                if event_type == "session.start" and session_id:
                    conn.execute(
                        """INSERT OR IGNORE INTO sessions
                           (id, project_id, agent_name, user_id, started_at, tags)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (
                            session_id, project_id,
                            event.get("agent_name", "default"),
                            event.get("user_id"),
                            event.get("timestamp", time.time()),
                            json.dumps(event.get("tags", {})),
                        ),
                    )
                elif event_type == "session.end" and session_id:
                    meta = event.get("meta", {})
                    conn.execute(
                        """UPDATE sessions SET
                           ended_at=?, success=?,
                           total_cost_usd=?, total_tokens=?,
                           total_llm_calls=?, total_tool_calls=?,
                           total_steps=?, error_count=?
                           WHERE id=?""",
                        (
                            event.get("timestamp"),
                            1 if event.get("success") else 0,
                            meta.get("total_cost", 0),
                            meta.get("total_tokens", 0),
                            meta.get("llm_calls", 0),
                            meta.get("tool_calls", 0),
                            meta.get("steps", 0),
                            meta.get("errors", 0),
                            session_id,
                        ),
                    )

                conn.execute(
                    """INSERT OR IGNORE INTO events
                       (id, session_id, project_id, agent_name, user_id, event_type, timestamp,
                        model, provider, prompt, completion,
                        input_tokens, output_tokens, total_tokens, cost_usd, latency_ms,
                        tool_name, tool_args, tool_result,
                        thought, decision, step_number,
                        error_message, error_type, stack_trace,
                        success, duration_ms, parent_id, tags, meta)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        event_id, session_id, project_id,
                        event.get("agent_name", "unknown"),
                        event.get("user_id"),
                        event_type,
                        event.get("timestamp", time.time()),
                        event.get("model"),
                        event.get("provider"),
                        event.get("prompt"),
                        event.get("completion"),
                        event.get("input_tokens"),
                        event.get("output_tokens"),
                        event.get("total_tokens"),
                        event.get("cost_usd"),
                        event.get("latency_ms"),
                        event.get("tool_name"),
                        json.dumps(event.get("tool_args")) if event.get("tool_args") else None,
                        event.get("tool_result"),
                        event.get("thought"),
                        event.get("decision"),
                        event.get("step_number"),
                        event.get("error_message"),
                        event.get("error_type"),
                        event.get("stack_trace"),
                        1 if event.get("success") else (0 if event.get("success") is False else None),
                        event.get("duration_ms"),
                        event.get("parent_id"),
                        json.dumps(event.get("tags", {})),
                        json.dumps(event.get("meta", {})),
                    ),
                )
                inserted += 1
            conn.commit()

        await loop.run_in_executor(None, _bulk_insert)
    return inserted


# ─── Queries ─────────────────────────────────────────────────


async def get_sessions(
    project_id: str = "default",
    agent_name: Optional[str] = None,
    user_id: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """Returns (sessions, total_count) for pagination."""
    db = await get_pool()

    count_q = "SELECT COUNT(*) FROM sessions WHERE project_id = ?"
    params: list = [project_id]
    if agent_name:
        count_q += " AND agent_name = ?"
        params.append(agent_name)
    if user_id:
        count_q += " AND user_id = ?"
        params.append(user_id)
    total = await db.fetchval(count_q, tuple(params)) or 0

    data_q = "SELECT * FROM sessions WHERE project_id = ?"
    params2: list = [project_id]
    if agent_name:
        data_q += " AND agent_name = ?"
        params2.append(agent_name)
    if user_id:
        data_q += " AND user_id = ?"
        params2.append(user_id)
    data_q += " ORDER BY started_at DESC LIMIT ? OFFSET ?"
    params2.extend([limit, offset])

    rows = await db.fetchall(data_q, tuple(params2))
    return rows, total


async def get_session(session_id: str) -> Optional[dict]:
    db = await get_pool()
    return await db.fetchone("SELECT * FROM sessions WHERE id = ?", (session_id,))


async def get_session_events(session_id: str) -> list[dict]:
    db = await get_pool()
    return await db.fetchall(
        "SELECT * FROM events WHERE session_id = ? ORDER BY timestamp ASC",
        (session_id,),
    )


async def get_events(
    project_id: str = "default",
    event_type: Optional[str] = None,
    limit: int = 100,
    since: Optional[float] = None,
) -> list[dict]:
    db = await get_pool()
    query = "SELECT * FROM events WHERE project_id = ?"
    params: list = [project_id]
    if event_type:
        query += " AND event_type = ?"
        params.append(event_type)
    if since:
        query += " AND timestamp > ?"
        params.append(since)
    query += " ORDER BY timestamp DESC LIMIT ?"
    params.append(limit)
    return await db.fetchall(query, tuple(params))


async def get_analytics(project_id: str = "default", hours: int = 24) -> dict:
    """Aggregated analytics with error breakdown and P95 latency."""
    db = await get_pool()
    since = time.time() - (hours * 3600)

    total_sessions = await db.fetchval(
        "SELECT COUNT(*) FROM sessions WHERE project_id=? AND started_at>?", (project_id, since)
    ) or 0
    success_sessions = await db.fetchval(
        "SELECT COUNT(*) FROM sessions WHERE project_id=? AND started_at>? AND success=1", (project_id, since)
    ) or 0
    failed_sessions = await db.fetchval(
        "SELECT COUNT(*) FROM sessions WHERE project_id=? AND started_at>? AND success=0", (project_id, since)
    ) or 0
    total_cost = await db.fetchval(
        "SELECT COALESCE(SUM(cost_usd),0) FROM events WHERE project_id=? AND timestamp>? AND cost_usd IS NOT NULL",
        (project_id, since),
    ) or 0
    total_tokens = await db.fetchval(
        "SELECT COALESCE(SUM(total_tokens),0) FROM events WHERE project_id=? AND timestamp>? AND total_tokens IS NOT NULL",
        (project_id, since),
    ) or 0
    llm_calls = await db.fetchval(
        "SELECT COUNT(*) FROM events WHERE project_id=? AND timestamp>? AND event_type='llm.response'",
        (project_id, since),
    ) or 0
    tool_calls = await db.fetchval(
        "SELECT COUNT(*) FROM events WHERE project_id=? AND timestamp>? AND event_type IN ('tool.result','tool.error')",
        (project_id, since),
    ) or 0
    errors = await db.fetchval(
        "SELECT COUNT(*) FROM events WHERE project_id=? AND timestamp>? AND event_type IN ('error','tool.error','llm.error')",
        (project_id, since),
    ) or 0
    avg_latency = await db.fetchval(
        "SELECT AVG(latency_ms) FROM events WHERE project_id=? AND timestamp>? AND latency_ms IS NOT NULL",
        (project_id, since),
    )
    avg_latency = round(avg_latency, 1) if avg_latency else 0

    p95_latency = await db.fetchval(
        """SELECT latency_ms FROM events
           WHERE project_id=? AND timestamp>? AND latency_ms IS NOT NULL
           ORDER BY latency_ms DESC
           LIMIT 1 OFFSET (
               SELECT CAST(COUNT(*)*0.05 AS INTEGER)
               FROM events WHERE project_id=? AND timestamp>? AND latency_ms IS NOT NULL
           )""",
        (project_id, since, project_id, since),
    )
    p95_latency = round(p95_latency, 1) if p95_latency else 0

    models = await db.fetchall(
        """SELECT model, COUNT(*) as count, SUM(COALESCE(cost_usd,0)) as cost,
           SUM(COALESCE(total_tokens,0)) as tokens, AVG(latency_ms) as avg_latency
           FROM events WHERE project_id=? AND timestamp>? AND model IS NOT NULL
           GROUP BY model ORDER BY count DESC LIMIT 10""",
        (project_id, since),
    )
    tools = await db.fetchall(
        """SELECT tool_name, COUNT(*) as count,
           SUM(CASE WHEN success=1 THEN 1 ELSE 0 END) as successes,
           SUM(CASE WHEN success=0 THEN 1 ELSE 0 END) as failures,
           AVG(duration_ms) as avg_duration
           FROM events WHERE project_id=? AND timestamp>?
           AND tool_name IS NOT NULL AND event_type IN ('tool.result','tool.error')
           GROUP BY tool_name ORDER BY count DESC LIMIT 10""",
        (project_id, since),
    )
    agents = await db.fetchall(
        """SELECT agent_name, COUNT(*) as sessions,
           SUM(CASE WHEN success=1 THEN 1 ELSE 0 END) as successes,
           SUM(CASE WHEN success=0 THEN 1 ELSE 0 END) as failures,
           SUM(total_cost_usd) as cost, SUM(total_tokens) as tokens, SUM(error_count) as errors
           FROM sessions WHERE project_id=? AND started_at>?
           GROUP BY agent_name ORDER BY sessions DESC""",
        (project_id, since),
    )
    error_types = await db.fetchall(
        """SELECT error_type, COUNT(*) as count, MAX(error_message) as last_message
           FROM events WHERE project_id=? AND timestamp>?
           AND event_type IN ('error','tool.error','llm.error') AND error_type IS NOT NULL
           GROUP BY error_type ORDER BY count DESC LIMIT 10""",
        (project_id, since),
    )

    return {
        "period_hours": hours,
        "total_sessions": total_sessions,
        "success_sessions": success_sessions,
        "failed_sessions": failed_sessions,
        "success_rate": round(success_sessions / max(total_sessions, 1) * 100, 1),
        "total_cost_usd": round(total_cost, 4),
        "total_tokens": total_tokens,
        "llm_calls": llm_calls,
        "tool_calls": tool_calls,
        "errors": errors,
        "avg_latency_ms": avg_latency,
        "p95_latency_ms": p95_latency,
        "top_models": models,
        "top_tools": tools,
        "agents": agents,
        "error_types": error_types,
    }


# ─── Alert Rules ─────────────────────────────────────────────


async def create_alert_rule(
    project_id: str, name: str, condition_type: str,
    threshold: float, webhook_url: str,
    window_minutes: int = 5, cooldown_minutes: int = 15,
) -> dict:
    import uuid
    rule_id = str(uuid.uuid4())
    db = await get_pool()
    await db.execute_write(
        """INSERT INTO alert_rules
           (id,project_id,name,condition_type,threshold,window_minutes,webhook_url,cooldown_minutes,created_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (rule_id, project_id, name, condition_type, threshold, window_minutes, webhook_url, cooldown_minutes, time.time()),
    )
    return {"id": rule_id, "name": name, "condition_type": condition_type, "threshold": threshold}


async def get_alert_rules(project_id: str = "default") -> list[dict]:
    db = await get_pool()
    return await db.fetchall(
        "SELECT * FROM alert_rules WHERE project_id=? AND enabled=1 ORDER BY created_at DESC",
        (project_id,),
    )


async def delete_alert_rule(rule_id: str):
    db = await get_pool()
    await db.execute_write("DELETE FROM alert_rules WHERE id=?", (rule_id,))


async def check_alert_conditions(project_id: str = "default") -> list[dict]:
    """Evaluate all alert rules and return triggered ones."""
    db = await get_pool()
    rules = await get_alert_rules(project_id)
    triggered = []
    now = time.time()

    for rule in rules:
        if now - rule["last_triggered_at"] < rule["cooldown_minutes"] * 60:
            continue
        window_start = now - rule["window_minutes"] * 60
        cond = rule["condition_type"]
        value = 0.0

        if cond == "error_rate":
            total = await db.fetchval(
                "SELECT COUNT(*) FROM sessions WHERE project_id=? AND started_at>?", (project_id, window_start)
            ) or 0
            failed = await db.fetchval(
                "SELECT COUNT(*) FROM sessions WHERE project_id=? AND started_at>? AND success=0", (project_id, window_start)
            ) or 0
            value = (failed / max(total, 1)) * 100
        elif cond == "latency":
            value = await db.fetchval(
                "SELECT AVG(latency_ms) FROM events WHERE project_id=? AND timestamp>? AND latency_ms IS NOT NULL",
                (project_id, window_start),
            ) or 0
        elif cond == "cost":
            value = await db.fetchval(
                "SELECT COALESCE(SUM(cost_usd),0) FROM events WHERE project_id=? AND timestamp>? AND cost_usd IS NOT NULL",
                (project_id, window_start),
            ) or 0
        elif cond == "failure_streak":
            recent = await db.fetchall(
                "SELECT success FROM sessions WHERE project_id=? ORDER BY started_at DESC LIMIT ?",
                (project_id, int(rule["threshold"])),
            )
            value = sum(1 for r in recent if r["success"] == 0)

        if value >= rule["threshold"]:
            triggered.append({"rule": rule, "value": value})
            await db.execute_write(
                "UPDATE alert_rules SET last_triggered_at=? WHERE id=?", (now, rule["id"])
            )
            await db.execute_write(
                "INSERT INTO alert_history (rule_id,triggered_at,condition_value) VALUES (?,?,?)",
                (rule["id"], now, value),
            )

    return triggered


async def get_alert_history(project_id: str = "default", limit: int = 50) -> list[dict]:
    db = await get_pool()
    return await db.fetchall(
        """SELECT ah.*, ar.name as rule_name, ar.condition_type, ar.threshold
           FROM alert_history ah JOIN alert_rules ar ON ah.rule_id=ar.id
           WHERE ar.project_id=? ORDER BY ah.triggered_at DESC LIMIT ?""",
        (project_id, limit),
    )


# ─── Data Retention ──────────────────────────────────────────


async def cleanup_old_data(days: int = 30) -> dict:
    """Delete events/sessions older than N days. VACUUM to reclaim space."""
    db = await get_pool()
    cutoff = time.time() - (days * 86400)

    events_deleted = await db.fetchval("SELECT COUNT(*) FROM events WHERE timestamp<?", (cutoff,)) or 0
    sessions_deleted = await db.fetchval("SELECT COUNT(*) FROM sessions WHERE started_at<?", (cutoff,)) or 0

    await db.execute_write("DELETE FROM events WHERE timestamp<?", (cutoff,))
    await db.execute_write("DELETE FROM sessions WHERE started_at<?", (cutoff,))

    logger.info(f"Cleanup: {events_deleted} events, {sessions_deleted} sessions older than {days}d")
    return {"events_deleted": events_deleted, "sessions_deleted": sessions_deleted, "cutoff_days": days}


async def get_db_stats() -> dict:
    db = await get_pool()
    event_count = await db.fetchval("SELECT COUNT(*) FROM events") or 0
    session_count = await db.fetchval("SELECT COUNT(*) FROM sessions") or 0
    db_size = os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 0
    return {
        "db_size_bytes": db_size,
        "db_size_mb": round(db_size / 1024 / 1024, 2),
        "total_events": event_count,
        "total_sessions": session_count,
        "event_count": event_count,
        "session_count": session_count,
    }


async def verify_api_key(api_key: str) -> Optional[str]:
    db = await get_pool()
    result = await db.fetchone("SELECT id FROM projects WHERE api_key=?", (api_key,))
    return result["id"] if result else None
