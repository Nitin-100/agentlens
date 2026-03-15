"""
AgentLens Cost Anomaly Detection — Automatic cost spike detection.

Zero-config: calculates rolling average cost per agent per day.
When cost spikes 2x above baseline, auto-fires webhooks.
No alert rules needed — it just works.

Also provides prompt similarity analysis for diff view.
"""

import time
import json
import asyncio
import logging
import hashlib
from typing import Optional
from collections import defaultdict

logger = logging.getLogger("agentlens.anomaly")


class CostAnomalyDetector:
    """Automatic cost anomaly detection with zero configuration."""

    def __init__(self, db_pool):
        self._pool = db_pool
        self._running = False
        self._task = None
        self._spike_multiplier = float(
            __import__("os").environ.get("AGENTLENS_COST_SPIKE_THRESHOLD", "2.0")
        )

    async def init_tables(self):
        """Create tables for cost baselines and anomaly history."""
        await self._pool.execute_write("""
            CREATE TABLE IF NOT EXISTS cost_baselines (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                agent_name TEXT NOT NULL,
                date TEXT NOT NULL,
                daily_cost REAL NOT NULL DEFAULT 0,
                daily_tokens INTEGER NOT NULL DEFAULT 0,
                llm_calls INTEGER NOT NULL DEFAULT 0,
                avg_cost_per_call REAL DEFAULT 0,
                rolling_avg_7d REAL DEFAULT 0,
                rolling_avg_30d REAL DEFAULT 0,
                UNIQUE(project_id, agent_name, date)
            )
        """)

        await self._pool.execute_write("""
            CREATE TABLE IF NOT EXISTS cost_anomalies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id TEXT NOT NULL,
                agent_name TEXT NOT NULL,
                detected_at REAL NOT NULL,
                anomaly_type TEXT NOT NULL,
                current_value REAL NOT NULL,
                baseline_value REAL NOT NULL,
                spike_ratio REAL NOT NULL,
                details TEXT,
                acknowledged INTEGER DEFAULT 0,
                webhook_sent INTEGER DEFAULT 0
            )
        """)

        await self._pool.execute_write("""
            CREATE INDEX IF NOT EXISTS idx_cost_baselines_lookup
            ON cost_baselines(project_id, agent_name, date)
        """)

        await self._pool.execute_write("""
            CREATE INDEX IF NOT EXISTS idx_cost_anomalies_project
            ON cost_anomalies(project_id, detected_at)
        """)

        logger.info("Cost anomaly detection tables initialized")

    async def update_baselines(self, project_id: str):
        """Update daily cost baselines for all agents in a project."""
        import uuid
        today = time.strftime("%Y-%m-%d")
        day_start = time.mktime(time.strptime(today, "%Y-%m-%d"))
        day_end = day_start + 86400

        # Get today's costs per agent
        agents = await self._pool.fetchall(
            """SELECT agent_name,
                      COALESCE(SUM(cost_usd), 0) as daily_cost,
                      COALESCE(SUM(total_tokens), 0) as daily_tokens,
                      COUNT(*) as llm_calls,
                      COALESCE(AVG(cost_usd), 0) as avg_cost_per_call
               FROM events
               WHERE project_id = ? AND timestamp >= ? AND timestamp < ?
                 AND event_type = 'llm.response' AND cost_usd IS NOT NULL
               GROUP BY agent_name""",
            (project_id, day_start, day_end),
        )

        for agent in agents:
            agent_name = agent["agent_name"]

            # Calculate rolling averages
            seven_days_ago = day_start - (7 * 86400)
            thirty_days_ago = day_start - (30 * 86400)

            avg_7d = await self._pool.fetchval(
                """SELECT AVG(daily_cost) FROM cost_baselines
                   WHERE project_id = ? AND agent_name = ? AND date >= ?""",
                (project_id, agent_name, time.strftime("%Y-%m-%d", time.localtime(seven_days_ago))),
            ) or 0

            avg_30d = await self._pool.fetchval(
                """SELECT AVG(daily_cost) FROM cost_baselines
                   WHERE project_id = ? AND agent_name = ? AND date >= ?""",
                (project_id, agent_name, time.strftime("%Y-%m-%d", time.localtime(thirty_days_ago))),
            ) or 0

            # Upsert baseline
            existing = await self._pool.fetchone(
                "SELECT id FROM cost_baselines WHERE project_id = ? AND agent_name = ? AND date = ?",
                (project_id, agent_name, today),
            )

            if existing:
                await self._pool.execute_write(
                    """UPDATE cost_baselines SET daily_cost=?, daily_tokens=?, llm_calls=?,
                       avg_cost_per_call=?, rolling_avg_7d=?, rolling_avg_30d=?
                       WHERE id=?""",
                    (agent["daily_cost"], agent["daily_tokens"], agent["llm_calls"],
                     agent["avg_cost_per_call"], avg_7d, avg_30d, existing["id"]),
                )
            else:
                await self._pool.execute_write(
                    """INSERT INTO cost_baselines
                       (id, project_id, agent_name, date, daily_cost, daily_tokens,
                        llm_calls, avg_cost_per_call, rolling_avg_7d, rolling_avg_30d)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (str(uuid.uuid4()), project_id, agent_name, today,
                     agent["daily_cost"], agent["daily_tokens"], agent["llm_calls"],
                     agent["avg_cost_per_call"], avg_7d, avg_30d),
                )

    async def detect_anomalies(self, project_id: str) -> list[dict]:
        """Detect cost anomalies for a project. Returns list of detected anomalies."""
        today = time.strftime("%Y-%m-%d")
        anomalies = []

        # Get today's baselines
        baselines = await self._pool.fetchall(
            "SELECT * FROM cost_baselines WHERE project_id = ? AND date = ?",
            (project_id, today),
        )

        for baseline in baselines:
            agent_name = baseline["agent_name"]
            current_cost = baseline["daily_cost"]
            avg_7d = baseline["rolling_avg_7d"]
            avg_30d = baseline["rolling_avg_30d"]

            # Skip if no meaningful baseline (need at least 3 days of data)
            historical_days = await self._pool.fetchval(
                "SELECT COUNT(DISTINCT date) FROM cost_baselines WHERE project_id=? AND agent_name=?",
                (project_id, agent_name),
            ) or 0

            if historical_days < 3:
                continue

            # Use 7-day average as primary baseline, fall back to 30-day
            baseline_cost = avg_7d if avg_7d > 0 else avg_30d
            if baseline_cost <= 0:
                continue

            spike_ratio = current_cost / baseline_cost

            # Cost spike detection
            if spike_ratio >= self._spike_multiplier:
                anomaly = {
                    "project_id": project_id,
                    "agent_name": agent_name,
                    "anomaly_type": "cost_spike",
                    "current_value": round(current_cost, 6),
                    "baseline_value": round(baseline_cost, 6),
                    "spike_ratio": round(spike_ratio, 2),
                    "details": json.dumps({
                        "daily_cost": current_cost,
                        "rolling_avg_7d": avg_7d,
                        "rolling_avg_30d": avg_30d,
                        "historical_days": historical_days,
                        "threshold_multiplier": self._spike_multiplier,
                    }),
                }

                # Check if already reported today
                existing = await self._pool.fetchone(
                    """SELECT id FROM cost_anomalies
                       WHERE project_id=? AND agent_name=? AND anomaly_type='cost_spike'
                       AND detected_at > ?""",
                    (project_id, agent_name, time.mktime(time.strptime(today, "%Y-%m-%d"))),
                )

                if not existing:
                    await self._pool.execute_write(
                        """INSERT INTO cost_anomalies
                           (project_id, agent_name, detected_at, anomaly_type,
                            current_value, baseline_value, spike_ratio, details)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (project_id, agent_name, time.time(), "cost_spike",
                         anomaly["current_value"], anomaly["baseline_value"],
                         anomaly["spike_ratio"], anomaly["details"]),
                    )
                    anomalies.append(anomaly)
                    logger.warning(
                        f"Cost anomaly detected: {agent_name} cost is {spike_ratio:.1f}x "
                        f"above baseline (${current_cost:.4f} vs ${baseline_cost:.4f})"
                    )

        return anomalies

    async def get_anomalies(self, project_id: str, limit: int = 50,
                             acknowledged: Optional[bool] = None) -> list[dict]:
        """Get cost anomaly history."""
        query = "SELECT * FROM cost_anomalies WHERE project_id = ?"
        params = [project_id]
        if acknowledged is not None:
            query += " AND acknowledged = ?"
            params.append(1 if acknowledged else 0)
        query += " ORDER BY detected_at DESC LIMIT ?"
        params.append(limit)
        return await self._pool.fetchall(query, tuple(params))

    async def acknowledge_anomaly(self, anomaly_id: int):
        """Mark an anomaly as acknowledged."""
        await self._pool.execute_write(
            "UPDATE cost_anomalies SET acknowledged = 1 WHERE id = ?",
            (anomaly_id,),
        )

    async def get_cost_trends(self, project_id: str, days: int = 30) -> list[dict]:
        """Get daily cost trends for all agents."""
        cutoff = time.strftime(
            "%Y-%m-%d",
            time.localtime(time.time() - (days * 86400))
        )
        return await self._pool.fetchall(
            """SELECT agent_name, date, daily_cost, daily_tokens, llm_calls,
                      rolling_avg_7d, rolling_avg_30d
               FROM cost_baselines
               WHERE project_id = ? AND date >= ?
               ORDER BY date ASC, agent_name""",
            (project_id, cutoff),
        )

    # ─── Auto-fire webhooks for anomalies ────────────────────

    async def _fire_anomaly_webhooks(self, project_id: str, anomalies: list[dict]):
        """Fire webhooks for detected anomalies using existing alert rules."""
        if not anomalies:
            return

        # Get all "cost" alert rules for this project
        rules = await self._pool.fetchall(
            """SELECT * FROM alert_rules
               WHERE project_id = ? AND condition_type = 'cost' AND enabled = 1""",
            (project_id,),
        )

        for anomaly in anomalies:
            for rule in rules:
                payload = {
                    "alert": f"Cost Anomaly: {anomaly['agent_name']}",
                    "type": "cost_anomaly",
                    "agent": anomaly["agent_name"],
                    "current_cost": anomaly["current_value"],
                    "baseline_cost": anomaly["baseline_value"],
                    "spike_ratio": anomaly["spike_ratio"],
                    "project": project_id,
                    "timestamp": time.time(),
                    "message": (
                        f"[AgentLens] Cost anomaly detected for '{anomaly['agent_name']}': "
                        f"${anomaly['current_value']:.4f}/day vs ${anomaly['baseline_value']:.4f}/day baseline "
                        f"({anomaly['spike_ratio']:.1f}x spike)"
                    ),
                }

                try:
                    from urllib.request import Request, urlopen
                    data = json.dumps(payload).encode("utf-8")
                    req = Request(
                        rule["webhook_url"], data=data,
                        headers={"Content-Type": "application/json"}, method="POST"
                    )
                    with urlopen(req, timeout=10) as resp:
                        logger.info(f"Cost anomaly webhook fired: {rule['webhook_url']} → {resp.status}")
                except Exception as e:
                    logger.error(f"Cost anomaly webhook failed: {e}")

    # ─── Background loop ─────────────────────────────────────

    def start_background_detection(self, interval_seconds: int = 300):
        """Start background anomaly detection (default: every 5 min)."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._detection_loop(interval_seconds))
        logger.info(f"Cost anomaly detection started (every {interval_seconds}s)")

    def stop_background_detection(self):
        self._running = False
        if self._task:
            self._task.cancel()

    async def _detection_loop(self, interval: int):
        while self._running:
            await asyncio.sleep(interval)
            try:
                projects = await self._pool.fetchall("SELECT id FROM projects")
                for project in projects:
                    pid = project["id"]
                    await self.update_baselines(pid)
                    anomalies = await self.detect_anomalies(pid)
                    if anomalies:
                        await self._fire_anomaly_webhooks(pid, anomalies)
            except Exception as e:
                logger.error(f"Anomaly detection error: {e}")


# ─── Prompt Similarity ───────────────────────────────────────

def compute_similarity(text_a: str, text_b: str) -> float:
    """Compute similarity between two texts using character-level n-gram Jaccard.
    Returns 0.0 to 1.0. This is fast, zero-dependency, and good enough for prompt diffing.
    """
    if not text_a or not text_b:
        return 0.0
    if text_a == text_b:
        return 1.0

    n = 3  # trigrams
    def ngrams(text):
        text = text.lower().strip()
        return set(text[i:i+n] for i in range(max(len(text) - n + 1, 1)))

    set_a = ngrams(text_a)
    set_b = ngrams(text_b)

    if not set_a or not set_b:
        return 0.0

    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union > 0 else 0.0


def compute_diff(text_a: str, text_b: str) -> list[dict]:
    """Compute a simple line-level diff between two texts.
    Returns list of {type: 'same'|'added'|'removed', line: str}.
    """
    lines_a = (text_a or "").splitlines()
    lines_b = (text_b or "").splitlines()

    # Simple LCS-based diff
    result = []
    i, j = 0, 0
    set_a = set(lines_a)
    set_b = set(lines_b)

    while i < len(lines_a) or j < len(lines_b):
        if i < len(lines_a) and j < len(lines_b) and lines_a[i] == lines_b[j]:
            result.append({"type": "same", "line": lines_a[i]})
            i += 1
            j += 1
        elif i < len(lines_a) and (j >= len(lines_b) or lines_a[i] not in set_b):
            result.append({"type": "removed", "line": lines_a[i]})
            i += 1
        elif j < len(lines_b) and (i >= len(lines_a) or lines_b[j] not in set_a):
            result.append({"type": "added", "line": lines_b[j]})
            j += 1
        else:
            # Both have unique lines — output both
            if i < len(lines_a):
                result.append({"type": "removed", "line": lines_a[i]})
                i += 1
            if j < len(lines_b):
                result.append({"type": "added", "line": lines_b[j]})
                j += 1

    return result
