"""
AgentLens Data Retention — Automated data lifecycle management.

Features:
  - Per-project retention policies (configurable days)
  - Global default retention policy
  - Automated background purge (runs every hour)
  - Retention policy CRUD API
  - Audit trail of all purges
  - Configurable: AGENTLENS_RETENTION_DAYS env var (default: 90)
"""

import os
import time
import json
import asyncio
import logging
from typing import Optional

logger = logging.getLogger("agentlens.retention")

DEFAULT_RETENTION_DAYS = int(os.environ.get("AGENTLENS_RETENTION_DAYS", "90"))


class RetentionManager:
    """Manages data retention policies and automated cleanup."""

    def __init__(self, db_pool, auth_manager=None):
        self._pool = db_pool
        self._auth = auth_manager
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def init_tables(self):
        """Create retention policy table."""
        await self._pool.execute_write("""
            CREATE TABLE IF NOT EXISTS retention_policies (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL UNIQUE,
                retention_days INTEGER NOT NULL DEFAULT 90,
                delete_events INTEGER DEFAULT 1,
                delete_sessions INTEGER DEFAULT 1,
                delete_audit_logs INTEGER DEFAULT 0,
                last_purge_at REAL,
                total_events_purged INTEGER DEFAULT 0,
                total_sessions_purged INTEGER DEFAULT 0,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                FOREIGN KEY (project_id) REFERENCES projects(id)
            )
        """)

        await self._pool.execute_write("""
            CREATE TABLE IF NOT EXISTS retention_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id TEXT NOT NULL,
                purge_timestamp REAL NOT NULL,
                events_deleted INTEGER DEFAULT 0,
                sessions_deleted INTEGER DEFAULT 0,
                audit_entries_deleted INTEGER DEFAULT 0,
                cutoff_timestamp REAL NOT NULL,
                duration_ms REAL,
                error TEXT
            )
        """)

        await self._pool.execute_write("""
            CREATE INDEX IF NOT EXISTS idx_retention_log_project
            ON retention_log(project_id)
        """)

        logger.info(f"Retention tables initialized (default: {DEFAULT_RETENTION_DAYS} days)")

    async def set_policy(self, project_id: str, retention_days: int,
                         delete_events: bool = True, delete_sessions: bool = True,
                         delete_audit_logs: bool = False) -> dict:
        """Set or update retention policy for a project."""
        import uuid
        now = time.time()

        existing = await self._pool.fetchone(
            "SELECT id FROM retention_policies WHERE project_id = ?",
            (project_id,),
        )

        if existing:
            await self._pool.execute_write(
                """UPDATE retention_policies
                   SET retention_days=?, delete_events=?, delete_sessions=?,
                       delete_audit_logs=?, updated_at=?
                   WHERE project_id=?""",
                (retention_days, int(delete_events), int(delete_sessions),
                 int(delete_audit_logs), now, project_id),
            )
            policy_id = existing["id"]
        else:
            policy_id = str(uuid.uuid4())
            await self._pool.execute_write(
                """INSERT INTO retention_policies
                   (id, project_id, retention_days, delete_events, delete_sessions,
                    delete_audit_logs, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (policy_id, project_id, retention_days, int(delete_events),
                 int(delete_sessions), int(delete_audit_logs), now, now),
            )

        logger.info(f"Retention policy set: project={project_id}, days={retention_days}")
        return {
            "id": policy_id,
            "project_id": project_id,
            "retention_days": retention_days,
            "delete_events": delete_events,
            "delete_sessions": delete_sessions,
            "delete_audit_logs": delete_audit_logs,
        }

    async def get_policy(self, project_id: str) -> dict:
        """Get retention policy for a project. Returns default if none set."""
        policy = await self._pool.fetchone(
            "SELECT * FROM retention_policies WHERE project_id = ?",
            (project_id,),
        )
        if policy:
            return dict(policy)
        return {
            "project_id": project_id,
            "retention_days": DEFAULT_RETENTION_DAYS,
            "delete_events": True,
            "delete_sessions": True,
            "delete_audit_logs": False,
            "is_default": True,
        }

    async def get_all_policies(self) -> list[dict]:
        """List all retention policies."""
        return await self._pool.fetchall(
            "SELECT * FROM retention_policies ORDER BY project_id"
        )

    async def delete_policy(self, project_id: str) -> bool:
        """Remove custom policy (reverts to default)."""
        await self._pool.execute_write(
            "DELETE FROM retention_policies WHERE project_id = ?",
            (project_id,),
        )
        return True

    async def purge_project(self, project_id: str, retention_days: Optional[int] = None) -> dict:
        """Purge old data for a specific project based on its retention policy."""
        start = time.time()

        if retention_days is None:
            policy = await self.get_policy(project_id)
            retention_days = policy["retention_days"]
            delete_events = policy.get("delete_events", True)
            delete_sessions = policy.get("delete_sessions", True)
            delete_audit = policy.get("delete_audit_logs", False)
        else:
            delete_events = True
            delete_sessions = True
            delete_audit = False

        cutoff = time.time() - (retention_days * 86400)
        events_deleted = 0
        sessions_deleted = 0
        audit_deleted = 0

        try:
            if delete_events:
                events_deleted = await self._pool.fetchval(
                    "SELECT COUNT(*) FROM events WHERE project_id=? AND timestamp<?",
                    (project_id, cutoff),
                ) or 0
                if events_deleted > 0:
                    await self._pool.execute_write(
                        "DELETE FROM events WHERE project_id=? AND timestamp<?",
                        (project_id, cutoff),
                    )

            if delete_sessions:
                sessions_deleted = await self._pool.fetchval(
                    "SELECT COUNT(*) FROM sessions WHERE project_id=? AND started_at<?",
                    (project_id, cutoff),
                ) or 0
                if sessions_deleted > 0:
                    await self._pool.execute_write(
                        "DELETE FROM sessions WHERE project_id=? AND started_at<?",
                        (project_id, cutoff),
                    )

            if delete_audit:
                audit_deleted = await self._pool.fetchval(
                    "SELECT COUNT(*) FROM audit_log WHERE project_id=? AND timestamp<?",
                    (project_id, cutoff),
                ) or 0
                if audit_deleted > 0:
                    await self._pool.execute_write(
                        "DELETE FROM audit_log WHERE project_id=? AND timestamp<?",
                        (project_id, cutoff),
                    )

            duration_ms = (time.time() - start) * 1000

            # Update policy stats
            await self._pool.execute_write(
                """UPDATE retention_policies
                   SET last_purge_at=?,
                       total_events_purged=total_events_purged+?,
                       total_sessions_purged=total_sessions_purged+?
                   WHERE project_id=?""",
                (time.time(), events_deleted, sessions_deleted, project_id),
            )

            # Log the purge
            await self._pool.execute_write(
                """INSERT INTO retention_log
                   (project_id, purge_timestamp, events_deleted, sessions_deleted,
                    audit_entries_deleted, cutoff_timestamp, duration_ms)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (project_id, time.time(), events_deleted, sessions_deleted,
                 audit_deleted, cutoff, duration_ms),
            )

            if events_deleted or sessions_deleted or audit_deleted:
                logger.info(
                    f"Purge complete: project={project_id}, "
                    f"events={events_deleted}, sessions={sessions_deleted}, "
                    f"audit={audit_deleted}, took={duration_ms:.1f}ms"
                )

            return {
                "project_id": project_id,
                "retention_days": retention_days,
                "events_deleted": events_deleted,
                "sessions_deleted": sessions_deleted,
                "audit_entries_deleted": audit_deleted,
                "cutoff_timestamp": cutoff,
                "duration_ms": round(duration_ms, 1),
            }

        except Exception as e:
            duration_ms = (time.time() - start) * 1000
            await self._pool.execute_write(
                """INSERT INTO retention_log
                   (project_id, purge_timestamp, cutoff_timestamp, duration_ms, error)
                   VALUES (?, ?, ?, ?, ?)""",
                (project_id, time.time(), cutoff, duration_ms, str(e)),
            )
            logger.error(f"Purge failed for project={project_id}: {e}")
            raise

    async def purge_all_projects(self) -> list[dict]:
        """Run purge for all projects based on their policies."""
        projects = await self._pool.fetchall("SELECT id FROM projects")
        results = []
        for project in projects:
            try:
                result = await self.purge_project(project["id"])
                results.append(result)
            except Exception as e:
                results.append({"project_id": project["id"], "error": str(e)})
        return results

    async def get_purge_history(self, project_id: Optional[str] = None,
                                 limit: int = 50) -> list[dict]:
        """Get retention purge history."""
        if project_id:
            return await self._pool.fetchall(
                "SELECT * FROM retention_log WHERE project_id=? ORDER BY purge_timestamp DESC LIMIT ?",
                (project_id, limit),
            )
        return await self._pool.fetchall(
            "SELECT * FROM retention_log ORDER BY purge_timestamp DESC LIMIT ?",
            (limit,),
        )

    # ─── Background Auto-Purge ───────────────────────────────

    def start_background_purge(self, interval_seconds: int = 3600):
        """Start automated purge loop (default: every hour)."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._purge_loop(interval_seconds))
        logger.info(f"Background retention purge started (every {interval_seconds}s)")

    def stop_background_purge(self):
        """Stop the background purge loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None

    async def _purge_loop(self, interval: int):
        """Background loop that purges expired data."""
        while self._running:
            await asyncio.sleep(interval)
            try:
                results = await self.purge_all_projects()
                total_events = sum(r.get("events_deleted", 0) for r in results)
                total_sessions = sum(r.get("sessions_deleted", 0) for r in results)
                if total_events or total_sessions:
                    logger.info(
                        f"Auto-purge complete: {total_events} events, "
                        f"{total_sessions} sessions across {len(results)} projects"
                    )
            except Exception as e:
                logger.error(f"Auto-purge error: {e}")
