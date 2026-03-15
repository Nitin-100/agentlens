"""
Built-in AgentLens Plugins — ready-to-use database backends, exporters, and processors.

Database Plugins:
    - PostgreSQLPlugin    — Production PostgreSQL with connection pooling
    - ClickHousePlugin    — Columnar analytics database for massive scale
    - MongoDBPlugin       — Document store for flexible event data

Exporter Plugins:
    - S3Exporter          — Archive events to S3/MinIO as JSONL
    - WebhookExporter     — Forward events to any HTTP endpoint
    - FileExporter        — Write events to local JSONL files (log rotation)
    - KafkaExporter       — Stream events to Kafka topics
    - DataDogExporter     — Send metrics to DataDog

Event Processors:
    - PIIRedactor         — Redact emails, phone numbers, SSNs, API keys
    - SamplingProcessor   — Probabilistic event sampling
    - FilterProcessor     — Drop events by type/agent/field
    - EnrichmentProcessor — Add custom metadata to events
"""

import os
import re
import json
import time
import random
import logging
import asyncio
from typing import List, Optional
from datetime import datetime, timezone

from .plugins import DatabasePlugin, ExporterPlugin, EventProcessor

logger = logging.getLogger("agentlens.plugins.builtin")


# ──────────────────────────────────────────────────────────────
# DATABASE PLUGINS
# ──────────────────────────────────────────────────────────────

class PostgreSQLPlugin(DatabasePlugin):
    """PostgreSQL database backend with asyncpg connection pooling.

    Usage:
        from agentlens.builtin_plugins import PostgreSQLPlugin
        from agentlens.plugins import PluginRegistry

        pg = PostgreSQLPlugin(dsn="postgresql://user:pass@localhost:5432/agentlens")
        PluginRegistry.get_instance().register_database(pg)

    Requirements: pip install asyncpg
    """

    def __init__(self, dsn: str, pool_min: int = 2, pool_max: int = 10):
        self.dsn = dsn
        self.pool_min = pool_min
        self.pool_max = pool_max
        self._pool = None

    async def init(self) -> None:
        import asyncpg
        self._pool = await asyncpg.create_pool(
            self.dsn, min_size=self.pool_min, max_size=self.pool_max
        )
        # Create tables
        async with self._pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL DEFAULT 'default',
                    agent_name TEXT,
                    started_at DOUBLE PRECISION,
                    ended_at DOUBLE PRECISION,
                    success BOOLEAN,
                    total_cost_usd DOUBLE PRECISION DEFAULT 0,
                    total_tokens INTEGER DEFAULT 0,
                    total_llm_calls INTEGER DEFAULT 0,
                    total_tool_calls INTEGER DEFAULT 0,
                    total_steps INTEGER DEFAULT 0,
                    error_count INTEGER DEFAULT 0,
                    input_data TEXT,
                    output_data TEXT,
                    tags JSONB DEFAULT '{}'::jsonb,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    id TEXT PRIMARY KEY,
                    session_id TEXT REFERENCES sessions(id),
                    project_id TEXT NOT NULL DEFAULT 'default',
                    event_type TEXT NOT NULL,
                    agent_name TEXT,
                    timestamp DOUBLE PRECISION NOT NULL,
                    data JSONB DEFAULT '{}'::jsonb,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_events_ts ON events(timestamp)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_agent ON sessions(agent_name)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_ts ON sessions(started_at)")
        logger.info("PostgreSQL plugin initialized")

    async def insert_events(self, events: List[dict]) -> int:
        if not events:
            return 0
        async with self._pool.acquire() as conn:
            for event in events:
                await conn.execute(
                    """INSERT INTO events (id, session_id, project_id, event_type, agent_name, timestamp, data)
                       VALUES ($1, $2, $3, $4, $5, $6, $7)
                       ON CONFLICT (id) DO NOTHING""",
                    event.get("event_id", str(time.time())),
                    event.get("session_id", ""),
                    event.get("project_id", "default"),
                    event.get("event_type", "unknown"),
                    event.get("agent_name", ""),
                    event.get("timestamp", time.time()),
                    json.dumps({k: v for k, v in event.items()
                               if k not in ("event_id", "session_id", "project_id", "event_type", "agent_name", "timestamp")},
                              default=str),
                )
        return len(events)

    async def insert_session(self, session: dict) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO sessions (id, project_id, agent_name, started_at, ended_at, success,
                   total_cost_usd, total_tokens, total_llm_calls, total_tool_calls, total_steps,
                   error_count, input_data, output_data, tags)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)
                   ON CONFLICT (id) DO UPDATE SET
                   ended_at=EXCLUDED.ended_at, success=EXCLUDED.success,
                   total_cost_usd=EXCLUDED.total_cost_usd, total_tokens=EXCLUDED.total_tokens,
                   total_llm_calls=EXCLUDED.total_llm_calls, total_tool_calls=EXCLUDED.total_tool_calls,
                   total_steps=EXCLUDED.total_steps, error_count=EXCLUDED.error_count,
                   output_data=EXCLUDED.output_data""",
                session.get("id", ""), session.get("project_id", "default"),
                session.get("agent_name", ""), session.get("started_at"),
                session.get("ended_at"), session.get("success"),
                session.get("total_cost_usd", 0), session.get("total_tokens", 0),
                session.get("total_llm_calls", 0), session.get("total_tool_calls", 0),
                session.get("total_steps", 0), session.get("error_count", 0),
                session.get("input_data"), session.get("output_data"),
                json.dumps(session.get("tags", {})),
            )

    async def get_sessions(self, limit=50, offset=0, agent=None, project=None) -> dict:
        conditions = ["1=1"]
        params = []
        idx = 1
        if agent:
            conditions.append(f"agent_name ILIKE ${idx}")
            params.append(f"%{agent}%")
            idx += 1
        if project:
            conditions.append(f"project_id = ${idx}")
            params.append(project)
            idx += 1

        where = " AND ".join(conditions)
        async with self._pool.acquire() as conn:
            total = await conn.fetchval(f"SELECT COUNT(*) FROM sessions WHERE {where}", *params)
            rows = await conn.fetch(
                f"SELECT * FROM sessions WHERE {where} ORDER BY started_at DESC LIMIT ${idx} OFFSET ${idx+1}",
                *params, limit, offset
            )
        return {"sessions": [dict(r) for r in rows], "total": total, "limit": limit, "offset": offset}

    async def get_session_detail(self, session_id: str) -> dict:
        async with self._pool.acquire() as conn:
            session = await conn.fetchrow("SELECT * FROM sessions WHERE id = $1", session_id)
            events = await conn.fetch(
                "SELECT * FROM events WHERE session_id = $1 ORDER BY timestamp", session_id
            )
        if not session:
            return {"error": "Session not found"}
        return {
            "session": dict(session),
            "events": [dict(e) for e in events],
        }

    async def get_events(self, limit=100, event_type=None, session_id=None) -> List[dict]:
        conditions = ["1=1"]
        params = []
        idx = 1
        if event_type:
            conditions.append(f"event_type = ${idx}")
            params.append(event_type)
            idx += 1
        if session_id:
            conditions.append(f"session_id = ${idx}")
            params.append(session_id)
            idx += 1
        where = " AND ".join(conditions)
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT * FROM events WHERE {where} ORDER BY timestamp DESC LIMIT ${idx}",
                *params, limit
            )
        return [dict(r) for r in rows]

    async def get_analytics(self, hours=24, project=None) -> dict:
        cutoff = time.time() - (hours * 3600)
        async with self._pool.acquire() as conn:
            stats = await conn.fetchrow("""
                SELECT COUNT(*) as total_sessions,
                       SUM(total_cost_usd) as total_cost,
                       SUM(total_tokens) as total_tokens,
                       SUM(error_count) as total_errors,
                       AVG(CASE WHEN ended_at IS NOT NULL THEN (ended_at - started_at) * 1000 END) as avg_latency
                FROM sessions WHERE started_at >= $1
            """, cutoff)
        return dict(stats) if stats else {}

    async def cleanup(self, days=30) -> dict:
        cutoff = time.time() - (days * 86400)
        async with self._pool.acquire() as conn:
            del_events = await conn.execute("DELETE FROM events WHERE timestamp < $1", cutoff)
            del_sessions = await conn.execute("DELETE FROM sessions WHERE started_at < $1", cutoff)
        return {"deleted_events": del_events, "deleted_sessions": del_sessions}

    async def health_check(self) -> dict:
        try:
            async with self._pool.acquire() as conn:
                version = await conn.fetchval("SELECT version()")
            return {"status": "ok", "engine": "postgresql", "version": version}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()


class ClickHousePlugin(DatabasePlugin):
    """ClickHouse database backend for massive-scale analytics.

    Optimized for millions of events/day with columnar storage and
    fast aggregation queries.

    Usage:
        from agentlens.builtin_plugins import ClickHousePlugin
        ch = ClickHousePlugin(url="http://localhost:8123", database="agentlens")

    Requirements: pip install clickhouse-connect
    """

    def __init__(self, url: str = "http://localhost:8123", database: str = "agentlens",
                 username: str = "default", password: str = ""):
        self.url = url
        self.database = database
        self.username = username
        self.password = password
        self._client = None

    async def init(self) -> None:
        import clickhouse_connect
        self._client = clickhouse_connect.get_client(
            host=self.url.replace("http://", "").split(":")[0],
            port=int(self.url.split(":")[-1]) if ":" in self.url.split("//")[-1] else 8123,
            username=self.username,
            password=self.password,
        )
        self._client.command(f"CREATE DATABASE IF NOT EXISTS {self.database}")
        self._client.command(f"""
            CREATE TABLE IF NOT EXISTS {self.database}.events (
                event_id String,
                session_id String,
                project_id String,
                event_type LowCardinality(String),
                agent_name LowCardinality(String),
                timestamp Float64,
                data String,
                created_at DateTime DEFAULT now()
            ) ENGINE = MergeTree()
            ORDER BY (project_id, agent_name, timestamp)
            PARTITION BY toYYYYMM(toDateTime(toUInt32(timestamp)))
        """)
        self._client.command(f"""
            CREATE TABLE IF NOT EXISTS {self.database}.sessions (
                id String,
                project_id String,
                agent_name LowCardinality(String),
                started_at Float64,
                ended_at Nullable(Float64),
                success UInt8 DEFAULT 0,
                total_cost_usd Float64 DEFAULT 0,
                total_tokens UInt32 DEFAULT 0,
                error_count UInt32 DEFAULT 0,
                tags String DEFAULT '{{}}'
            ) ENGINE = ReplacingMergeTree()
            ORDER BY (project_id, id)
        """)
        logger.info("ClickHouse plugin initialized")

    async def insert_events(self, events: List[dict]) -> int:
        if not events or not self._client:
            return 0
        data = []
        for e in events:
            data.append([
                e.get("event_id", ""), e.get("session_id", ""),
                e.get("project_id", "default"), e.get("event_type", ""),
                e.get("agent_name", ""), e.get("timestamp", time.time()),
                json.dumps({k: v for k, v in e.items()
                           if k not in ("event_id", "session_id", "project_id", "event_type", "agent_name", "timestamp")},
                          default=str),
            ])
        self._client.insert(f"{self.database}.events", data,
                           column_names=["event_id", "session_id", "project_id", "event_type", "agent_name", "timestamp", "data"])
        return len(data)

    async def insert_session(self, session: dict) -> None:
        if not self._client:
            return
        self._client.insert(f"{self.database}.sessions",
            [[session.get("id", ""), session.get("project_id", "default"),
              session.get("agent_name", ""), session.get("started_at", 0),
              session.get("ended_at"), 1 if session.get("success") else 0,
              session.get("total_cost_usd", 0), session.get("total_tokens", 0),
              session.get("error_count", 0), json.dumps(session.get("tags", {}))]],
            column_names=["id", "project_id", "agent_name", "started_at", "ended_at",
                         "success", "total_cost_usd", "total_tokens", "error_count", "tags"])

    async def get_sessions(self, limit=50, offset=0, agent=None, project=None) -> dict:
        where = "1=1"
        if agent:
            where += f" AND agent_name LIKE '%{agent}%'"
        if project:
            where += f" AND project_id = '{project}'"
        rows = self._client.query(
            f"SELECT * FROM {self.database}.sessions WHERE {where} ORDER BY started_at DESC LIMIT {limit} OFFSET {offset}"
        )
        total = self._client.query(f"SELECT COUNT() FROM {self.database}.sessions WHERE {where}")
        return {"sessions": [dict(zip(rows.column_names, r)) for r in rows.result_rows],
                "total": total.first_item.get("COUNT()", 0)}

    async def get_session_detail(self, session_id: str) -> dict:
        session = self._client.query(f"SELECT * FROM {self.database}.sessions WHERE id = '{session_id}'")
        events = self._client.query(
            f"SELECT * FROM {self.database}.events WHERE session_id = '{session_id}' ORDER BY timestamp"
        )
        if not session.result_rows:
            return {"error": "Not found"}
        return {
            "session": dict(zip(session.column_names, session.result_rows[0])),
            "events": [dict(zip(events.column_names, r)) for r in events.result_rows],
        }

    async def get_events(self, limit=100, event_type=None, session_id=None) -> List[dict]:
        where = "1=1"
        if event_type:
            where += f" AND event_type = '{event_type}'"
        if session_id:
            where += f" AND session_id = '{session_id}'"
        rows = self._client.query(
            f"SELECT * FROM {self.database}.events WHERE {where} ORDER BY timestamp DESC LIMIT {limit}"
        )
        return [dict(zip(rows.column_names, r)) for r in rows.result_rows]

    async def get_analytics(self, hours=24, project=None) -> dict:
        cutoff = time.time() - (hours * 3600)
        result = self._client.query(f"""
            SELECT count() as total_sessions,
                   sum(total_cost_usd) as total_cost,
                   sum(total_tokens) as total_tokens,
                   sum(error_count) as total_errors
            FROM {self.database}.sessions WHERE started_at >= {cutoff}
        """)
        if result.result_rows:
            row = dict(zip(result.column_names, result.result_rows[0]))
            return row
        return {}

    async def cleanup(self, days=30) -> dict:
        cutoff = time.time() - (days * 86400)
        self._client.command(f"ALTER TABLE {self.database}.events DELETE WHERE timestamp < {cutoff}")
        self._client.command(f"ALTER TABLE {self.database}.sessions DELETE WHERE started_at < {cutoff}")
        return {"status": "cleanup_submitted"}

    async def health_check(self) -> dict:
        try:
            self._client.query("SELECT 1")
            return {"status": "ok", "engine": "clickhouse"}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    async def close(self) -> None:
        if self._client:
            self._client.close()


# ──────────────────────────────────────────────────────────────
# EXPORTER PLUGINS
# ──────────────────────────────────────────────────────────────

class S3Exporter(ExporterPlugin):
    """Export events to S3/MinIO as JSONL files, partitioned by date.

    Usage:
        from agentlens.builtin_plugins import S3Exporter
        exporter = S3Exporter(bucket="my-agentlens-data", prefix="events/")

    Requirements: pip install boto3
    """

    def __init__(self, bucket: str, prefix: str = "agentlens/",
                 region: str = "us-east-1", endpoint_url: str = None):
        self.bucket = bucket
        self.prefix = prefix
        self.region = region
        self.endpoint_url = endpoint_url
        self._client = None

    async def init(self) -> None:
        import boto3
        kwargs = {"region_name": self.region}
        if self.endpoint_url:
            kwargs["endpoint_url"] = self.endpoint_url
        self._client = boto3.client("s3", **kwargs)
        logger.info(f"S3 exporter initialized: s3://{self.bucket}/{self.prefix}")

    async def export_events(self, events: List[dict]) -> None:
        if not events or not self._client:
            return
        date_str = datetime.now(timezone.utc).strftime("%Y/%m/%d")
        timestamp = int(time.time())
        key = f"{self.prefix}{date_str}/events_{timestamp}.jsonl"

        body = "\n".join(json.dumps(e, default=str) for e in events)
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: self._client.put_object(Bucket=self.bucket, Key=key, Body=body.encode(),
                                            ContentType="application/x-ndjson")
        )
        logger.debug(f"Exported {len(events)} events to s3://{self.bucket}/{key}")


class WebhookExporter(ExporterPlugin):
    """Forward events to any HTTP/HTTPS endpoint.

    Supports: Slack, Discord, PagerDuty, custom APIs, n8n, Zapier.

    Usage:
        exporter = WebhookExporter(url="https://hooks.slack.com/...", headers={"Content-Type": "application/json"})
    """

    def __init__(self, url: str, headers: dict = None, method: str = "POST",
                 batch: bool = True, filter_types: List[str] = None):
        self.url = url
        self.headers = headers or {"Content-Type": "application/json"}
        self.method = method
        self.batch = batch
        self.filter_types = filter_types  # Only forward these event types

    async def export_events(self, events: List[dict]) -> None:
        if self.filter_types:
            events = [e for e in events if e.get("event_type") in self.filter_types]
        if not events:
            return

        from urllib.request import Request, urlopen
        payload = json.dumps({"events": events} if self.batch else events[0], default=str).encode()
        req = Request(self.url, data=payload, headers=self.headers, method=self.method)

        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(None, lambda: urlopen(req, timeout=10))
        except Exception as e:
            logger.error(f"Webhook export failed: {e}")

    async def export_alert(self, alert: dict) -> None:
        from urllib.request import Request, urlopen
        payload = json.dumps({"alert": alert}, default=str).encode()
        req = Request(self.url, data=payload, headers=self.headers, method="POST")
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, lambda: urlopen(req, timeout=10))
        except Exception as e:
            logger.error(f"Webhook alert export failed: {e}")


class FileExporter(ExporterPlugin):
    """Write events to local JSONL files with date-based rotation.

    Usage:
        exporter = FileExporter(directory="./logs/agentlens")
    """

    def __init__(self, directory: str = "./agentlens_logs", max_file_mb: int = 100):
        self.directory = directory
        self.max_file_mb = max_file_mb

    async def init(self) -> None:
        os.makedirs(self.directory, exist_ok=True)

    async def export_events(self, events: List[dict]) -> None:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        filepath = os.path.join(self.directory, f"events_{date_str}.jsonl")

        # Check file size rotation
        if os.path.exists(filepath) and os.path.getsize(filepath) > self.max_file_mb * 1024 * 1024:
            rotated = filepath + f".{int(time.time())}"
            os.rename(filepath, rotated)

        with open(filepath, "a", encoding="utf-8") as f:
            for event in events:
                f.write(json.dumps(event, default=str) + "\n")


class KafkaExporter(ExporterPlugin):
    """Stream events to Apache Kafka topics.

    Usage:
        exporter = KafkaExporter(bootstrap_servers="localhost:9092", topic="agentlens.events")

    Requirements: pip install confluent-kafka
    """

    def __init__(self, bootstrap_servers: str, topic: str = "agentlens.events",
                 session_topic: str = "agentlens.sessions"):
        self.bootstrap_servers = bootstrap_servers
        self.topic = topic
        self.session_topic = session_topic
        self._producer = None

    async def init(self) -> None:
        from confluent_kafka import Producer
        self._producer = Producer({"bootstrap.servers": self.bootstrap_servers})
        logger.info(f"Kafka exporter initialized: {self.bootstrap_servers}")

    async def export_events(self, events: List[dict]) -> None:
        if not self._producer:
            return
        for event in events:
            self._producer.produce(
                self.topic,
                key=event.get("session_id", "").encode(),
                value=json.dumps(event, default=str).encode(),
            )
        self._producer.flush(timeout=5)

    async def export_session(self, session: dict) -> None:
        if not self._producer:
            return
        self._producer.produce(
            self.session_topic,
            key=session.get("id", "").encode(),
            value=json.dumps(session, default=str).encode(),
        )
        self._producer.flush(timeout=5)


# ──────────────────────────────────────────────────────────────
# EVENT PROCESSORS
# ──────────────────────────────────────────────────────────────

class PIIRedactor(EventProcessor):
    """Redact PII (emails, phone numbers, SSNs, API keys) from events before storage.

    Usage:
        from agentlens.builtin_plugins import PIIRedactor
        PluginRegistry.get_instance().register_processor(PIIRedactor())
    """

    PATTERNS = {
        "email": (re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'), "[EMAIL_REDACTED]"),
        "phone": (re.compile(r'\b(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)?\d{3}[-.\s]?\d{4}\b'), "[PHONE_REDACTED]"),
        "ssn": (re.compile(r'\b\d{3}-\d{2}-\d{4}\b'), "[SSN_REDACTED]"),
        "api_key": (re.compile(r'(?:sk|pk|api|key|token|secret|bearer)[-_]?[a-zA-Z0-9]{20,}', re.IGNORECASE), "[API_KEY_REDACTED]"),
        "credit_card": (re.compile(r'\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b'), "[CC_REDACTED]"),
    }

    def __init__(self, extra_patterns: dict = None):
        if extra_patterns:
            for name, (pattern, replacement) in extra_patterns.items():
                self.PATTERNS[name] = (re.compile(pattern) if isinstance(pattern, str) else pattern, replacement)

    def process(self, event: dict) -> dict:
        return self._redact_dict(event)

    def _redact_dict(self, d: dict) -> dict:
        result = {}
        for k, v in d.items():
            if isinstance(v, str):
                result[k] = self._redact_string(v)
            elif isinstance(v, dict):
                result[k] = self._redact_dict(v)
            elif isinstance(v, list):
                result[k] = [self._redact_dict(i) if isinstance(i, dict) else
                            self._redact_string(i) if isinstance(i, str) else i
                            for i in v]
            else:
                result[k] = v
        return result

    def _redact_string(self, s: str) -> str:
        for _, (pattern, replacement) in self.PATTERNS.items():
            s = pattern.sub(replacement, s)
        return s

    @property
    def priority(self) -> int:
        return 10  # Run early — redact before other processing


class SamplingProcessor(EventProcessor):
    """Probabilistic event sampling — drop events randomly to reduce volume.

    Usage:
        # Only keep 10% of events
        PluginRegistry.get_instance().register_processor(SamplingProcessor(rate=0.1))
    """

    def __init__(self, rate: float = 1.0, always_keep: List[str] = None):
        """
        Args:
            rate: Probability of keeping an event (0.0-1.0)
            always_keep: Event types to always keep (e.g., ["error", "session.end"])
        """
        self.rate = max(0.0, min(1.0, rate))
        self.always_keep = always_keep or ["error", "session.start", "session.end"]

    def process(self, event: dict) -> Optional[dict]:
        event_type = event.get("event_type", "")
        if event_type in self.always_keep:
            return event
        if random.random() <= self.rate:
            return event
        return None  # Drop

    @property
    def priority(self) -> int:
        return 5  # Run first — drop before any processing


class FilterProcessor(EventProcessor):
    """Filter events by type, agent, or custom predicate.

    Usage:
        # Drop all custom events
        PluginRegistry.get_instance().register_processor(
            FilterProcessor(drop_types=["custom"])
        )
    """

    def __init__(self, drop_types: List[str] = None, keep_types: List[str] = None,
                 drop_agents: List[str] = None, predicate: callable = None):
        self.drop_types = drop_types
        self.keep_types = keep_types
        self.drop_agents = drop_agents
        self.predicate = predicate

    def process(self, event: dict) -> Optional[dict]:
        event_type = event.get("event_type", "")
        agent = event.get("agent_name", "")

        if self.drop_types and event_type in self.drop_types:
            return None
        if self.keep_types and event_type not in self.keep_types:
            return None
        if self.drop_agents and agent in self.drop_agents:
            return None
        if self.predicate and not self.predicate(event):
            return None
        return event

    @property
    def priority(self) -> int:
        return 8


class EnrichmentProcessor(EventProcessor):
    """Add custom metadata to every event.

    Usage:
        PluginRegistry.get_instance().register_processor(
            EnrichmentProcessor(metadata={"environment": "production", "region": "us-east-1"})
        )
    """

    def __init__(self, metadata: dict = None, enricher: callable = None):
        """
        Args:
            metadata: Static fields to add to every event
            enricher: Function(event) -> dict of fields to add
        """
        self.metadata = metadata or {}
        self.enricher = enricher

    def process(self, event: dict) -> dict:
        event.update(self.metadata)
        if self.enricher:
            extra = self.enricher(event)
            if extra:
                event.update(extra)
        return event

    @property
    def priority(self) -> int:
        return 50  # Run after filtering but before export
