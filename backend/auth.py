"""
AgentLens Auth — RBAC, API key management, and multi-tenancy.

Roles:
  - admin: Full access. Manage users, projects, API keys, cleanup, alerts.
  - member: Read/write. Create sessions, ingest events, view analytics.
  - viewer: Read-only. View sessions, events, analytics. No mutations.

Multi-tenancy:
  - Each project has isolated data (events, sessions, alerts).
  - API keys are scoped to a project + role.
  - Rate limits apply per-project.
"""

import os
import time
import json
import uuid
import hashlib
import secrets
import sqlite3
import asyncio
import logging
from typing import Optional
from enum import Enum
from dataclasses import dataclass

logger = logging.getLogger("agentlens.auth")


class Role(str, Enum):
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


# Permission matrix: role → allowed actions
PERMISSIONS = {
    Role.ADMIN: {
        "events.ingest", "events.read",
        "sessions.read", "sessions.delete",
        "analytics.read",
        "alerts.create", "alerts.read", "alerts.delete",
        "admin.stats", "admin.cleanup", "admin.manage_keys",
        "projects.create", "projects.read", "projects.update", "projects.delete",
    },
    Role.MEMBER: {
        "events.ingest", "events.read",
        "sessions.read",
        "analytics.read",
        "alerts.create", "alerts.read", "alerts.delete",
    },
    Role.VIEWER: {
        "events.read",
        "sessions.read",
        "analytics.read",
        "alerts.read",
    },
}


@dataclass
class AuthContext:
    """Resolved auth context for a request."""
    project_id: str
    role: Role
    key_id: str
    key_name: str

    def has_permission(self, permission: str) -> bool:
        return permission in PERMISSIONS.get(self.role, set())


def hash_api_key(key: str) -> str:
    """SHA-256 hash for storing API keys (never store plaintext)."""
    return hashlib.sha256(key.encode()).hexdigest()


def generate_api_key(prefix: str = "al") -> str:
    """Generate a secure API key: al_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"""
    return f"{prefix}_{secrets.token_hex(24)}"


# ─── Schema ──────────────────────────────────────────────────

AUTH_SCHEMA = """
CREATE TABLE IF NOT EXISTS api_keys (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    name TEXT NOT NULL,
    key_hash TEXT NOT NULL UNIQUE,
    key_prefix TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'member',
    created_at REAL NOT NULL,
    last_used_at REAL,
    expires_at REAL,
    revoked INTEGER DEFAULT 0,
    created_by TEXT,
    FOREIGN KEY (project_id) REFERENCES projects(id)
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    project_id TEXT,
    key_id TEXT,
    action TEXT NOT NULL,
    resource TEXT,
    resource_id TEXT,
    ip_address TEXT,
    user_agent TEXT,
    details TEXT,
    success INTEGER DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_api_keys_hash ON api_keys(key_hash);
CREATE INDEX IF NOT EXISTS idx_api_keys_project ON api_keys(project_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_project ON audit_log(project_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_time ON audit_log(timestamp);
"""


def init_auth_tables(conn: sqlite3.Connection):
    """Create auth tables. Called during DB init."""
    conn.executescript(AUTH_SCHEMA)
    conn.commit()

    # Ensure default project has admin + member keys
    existing = conn.execute(
        "SELECT COUNT(*) FROM api_keys WHERE project_id='default'"
    ).fetchone()[0]
    if existing == 0:
        now = time.time()
        # Default admin key (for backwards compat)
        admin_key = "al_default_key"
        conn.execute(
            """INSERT OR IGNORE INTO api_keys (id, project_id, name, key_hash, key_prefix, role, created_at)
               VALUES (?, 'default', 'Default Admin Key', ?, 'al_de', 'admin', ?)""",
            (str(uuid.uuid4()), hash_api_key(admin_key), now),
        )
        conn.commit()
        logger.info("Default admin API key created: al_default_key")


# ─── Auth Resolution ─────────────────────────────────────────

class AuthManager:
    """Resolves API keys to auth contexts. Caches for performance."""

    def __init__(self, db_pool):
        self._pool = db_pool
        self._cache: dict[str, tuple[AuthContext, float]] = {}
        self._cache_ttl = 300  # 5 min

    async def resolve(self, authorization: Optional[str], x_project: Optional[str] = None) -> AuthContext:
        """Resolve auth from Authorization header.

        Supports:
          - Bearer <api_key>
          - No auth → default project as viewer (if AGENTLENS_REQUIRE_AUTH is not set)
        """
        require_auth = os.environ.get("AGENTLENS_REQUIRE_AUTH", "").lower() in ("1", "true", "yes")

        if not authorization or not authorization.startswith("Bearer "):
            if require_auth:
                raise PermissionError("Authentication required. Provide Authorization: Bearer <api_key>")
            return AuthContext(
                project_id=x_project or "default",
                role=Role.ADMIN,  # Backwards compat: no auth = full access
                key_id="anonymous",
                key_name="anonymous",
            )

        api_key = authorization[7:]
        return await self._resolve_key(api_key)

    async def _resolve_key(self, api_key: str) -> AuthContext:
        # Check cache
        key_hash = hash_api_key(api_key)
        cached = self._cache.get(key_hash)
        if cached and time.time() - cached[1] < self._cache_ttl:
            return cached[0]

        # Look up in DB
        row = await self._pool.fetchone(
            """SELECT id, project_id, name, role, expires_at, revoked
               FROM api_keys WHERE key_hash = ?""",
            (key_hash,),
        )

        if not row:
            raise PermissionError("Invalid API key")

        if row["revoked"]:
            raise PermissionError("API key has been revoked")

        if row["expires_at"] and row["expires_at"] < time.time():
            raise PermissionError("API key has expired")

        ctx = AuthContext(
            project_id=row["project_id"],
            role=Role(row["role"]),
            key_id=row["id"],
            key_name=row["name"],
        )

        # Update last_used_at (fire-and-forget)
        asyncio.create_task(self._update_last_used(row["id"]))

        # Cache it
        self._cache[key_hash] = (ctx, time.time())
        return ctx

    async def _update_last_used(self, key_id: str):
        try:
            await self._pool.execute_write(
                "UPDATE api_keys SET last_used_at = ? WHERE id = ?",
                (time.time(), key_id),
            )
        except Exception:
            pass  # Non-critical

    # ─── Key Management ──────────────────────────────────────

    async def create_key(
        self, project_id: str, name: str, role: str = "member",
        expires_days: Optional[int] = None, created_by: str = None,
    ) -> dict:
        """Create a new API key. Returns the plaintext key (only shown once)."""
        key_id = str(uuid.uuid4())
        api_key = generate_api_key()
        key_hash = hash_api_key(api_key)
        now = time.time()
        expires_at = now + (expires_days * 86400) if expires_days else None

        await self._pool.execute_write(
            """INSERT INTO api_keys (id, project_id, name, key_hash, key_prefix, role, created_at, expires_at, created_by)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (key_id, project_id, name, key_hash, api_key[:8], role, now, expires_at, created_by),
        )

        logger.info(f"API key created: {name} (project={project_id}, role={role})")
        return {
            "id": key_id,
            "key": api_key,  # Only returned once!
            "prefix": api_key[:8],
            "name": name,
            "project_id": project_id,
            "role": role,
            "expires_at": expires_at,
        }

    async def list_keys(self, project_id: str) -> list:
        """List API keys for a project (without sensitive data)."""
        return await self._pool.fetchall(
            """SELECT id, project_id, name, key_prefix, role, created_at, last_used_at, expires_at, revoked
               FROM api_keys WHERE project_id = ? ORDER BY created_at DESC""",
            (project_id,),
        )

    async def revoke_key(self, key_id: str, project_id: str) -> bool:
        """Revoke an API key."""
        await self._pool.execute_write(
            "UPDATE api_keys SET revoked = 1 WHERE id = ? AND project_id = ?",
            (key_id, project_id),
        )
        # Clear from cache
        self._cache = {k: v for k, v in self._cache.items() if v[0].key_id != key_id}
        logger.info(f"API key revoked: {key_id}")
        return True

    # ─── Key Rotation ────────────────────────────────────────

    async def rotate_key(self, key_id: str, project_id: str,
                         grace_period_hours: int = 24) -> dict:
        """Rotate an API key. Creates a new key, marks old one for expiry.

        The old key continues to work during the grace period (default: 24h).
        After the grace period, the old key expires automatically.

        Returns the new key (plaintext shown only once).
        """
        # Get old key info
        old_key = await self._pool.fetchone(
            "SELECT id, name, role FROM api_keys WHERE id = ? AND project_id = ?",
            (key_id, project_id),
        )
        if not old_key:
            raise ValueError("Key not found")

        # Create new key with same role and name
        new_name = f"{old_key['name']} (rotated)"
        new_key_result = await self.create_key(
            project_id=project_id,
            name=new_name,
            role=old_key["role"],
            created_by=key_id,
        )

        # Set old key to expire after grace period
        grace_expiry = time.time() + (grace_period_hours * 3600)
        await self._pool.execute_write(
            "UPDATE api_keys SET expires_at = ? WHERE id = ? AND project_id = ?",
            (grace_expiry, key_id, project_id),
        )

        # Clear old key from cache so it picks up the new expiry
        self._cache = {k: v for k, v in self._cache.items() if v[0].key_id != key_id}

        logger.info(
            f"Key rotated: {key_id} → {new_key_result['id']} "
            f"(grace period: {grace_period_hours}h)"
        )

        return {
            "new_key": new_key_result,
            "old_key_id": key_id,
            "old_key_expires_at": grace_expiry,
            "grace_period_hours": grace_period_hours,
        }

    async def rotate_all_project_keys(self, project_id: str,
                                        grace_period_hours: int = 24) -> list[dict]:
        """Rotate all active (non-revoked, non-expired) keys for a project."""
        keys = await self._pool.fetchall(
            """SELECT id FROM api_keys
               WHERE project_id = ? AND revoked = 0
               AND (expires_at IS NULL OR expires_at > ?)""",
            (project_id, time.time()),
        )
        results = []
        for key in keys:
            try:
                result = await self.rotate_key(key["id"], project_id, grace_period_hours)
                results.append(result)
            except Exception as e:
                results.append({"key_id": key["id"], "error": str(e)})
        return results

    # ─── Audit Logging ───────────────────────────────────────

    async def log_action(
        self, action: str, auth: AuthContext,
        resource: str = None, resource_id: str = None,
        ip: str = None, user_agent: str = None,
        details: str = None, success: bool = True,
    ):
        """Record an audit log entry."""
        try:
            await self._pool.execute_write(
                """INSERT INTO audit_log (timestamp, project_id, key_id, action, resource, resource_id,
                   ip_address, user_agent, details, success)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (time.time(), auth.project_id, auth.key_id, action, resource,
                 resource_id, ip, user_agent, details, 1 if success else 0),
            )
        except Exception:
            pass  # Audit logging should never break the request

    async def get_audit_log(self, project_id: str, limit: int = 100, action: str = None) -> list:
        """Retrieve audit log entries."""
        query = "SELECT * FROM audit_log WHERE project_id = ?"
        params = [project_id]
        if action:
            query += " AND action = ?"
            params.append(action)
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        return await self._pool.fetchall(query, tuple(params))


# ─── Project Management ──────────────────────────────────────

class ProjectManager:
    """Manage projects for multi-tenancy."""

    def __init__(self, db_pool):
        self._pool = db_pool

    async def create_project(self, name: str, settings: dict = None) -> dict:
        """Create a new project with auto-generated admin key."""
        project_id = name.lower().replace(" ", "-").replace("_", "-")
        now = time.time()

        await self._pool.execute_write(
            """INSERT INTO projects (id, name, api_key, created_at, settings)
               VALUES (?, ?, ?, ?, ?)""",
            (project_id, name, generate_api_key(), now, json.dumps(settings or {})),
        )

        logger.info(f"Project created: {project_id}")
        return {"id": project_id, "name": name, "created_at": now}

    async def list_projects(self) -> list:
        """List all projects."""
        return await self._pool.fetchall(
            "SELECT id, name, created_at, settings FROM projects ORDER BY created_at DESC"
        )

    async def get_project(self, project_id: str) -> Optional[dict]:
        return await self._pool.fetchone(
            "SELECT id, name, created_at, settings FROM projects WHERE id = ?",
            (project_id,),
        )

    async def update_project(self, project_id: str, settings: dict) -> bool:
        await self._pool.execute_write(
            "UPDATE projects SET settings = ? WHERE id = ?",
            (json.dumps(settings), project_id),
        )
        return True

    async def delete_project(self, project_id: str) -> dict:
        """Delete a project and ALL its data."""
        if project_id == "default":
            raise ValueError("Cannot delete default project")

        events = await self._pool.fetchval(
            "SELECT COUNT(*) FROM events WHERE project_id = ?", (project_id,)
        ) or 0
        sessions = await self._pool.fetchval(
            "SELECT COUNT(*) FROM sessions WHERE project_id = ?", (project_id,)
        ) or 0

        await self._pool.execute_write("DELETE FROM events WHERE project_id = ?", (project_id,))
        await self._pool.execute_write("DELETE FROM sessions WHERE project_id = ?", (project_id,))
        await self._pool.execute_write("DELETE FROM alert_rules WHERE project_id = ?", (project_id,))
        await self._pool.execute_write("DELETE FROM api_keys WHERE project_id = ?", (project_id,))
        await self._pool.execute_write("DELETE FROM projects WHERE id = ?", (project_id,))

        logger.info(f"Project deleted: {project_id} ({events} events, {sessions} sessions)")
        return {"deleted_events": events, "deleted_sessions": sessions}
