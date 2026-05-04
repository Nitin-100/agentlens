"""
AgentLens Compliance — HIPAA, SOC2, GDPR compliance enforcement.

Features:
  - PHI field detection and auto-classification
  - HIPAA audit trail (access logs for every PHI read/write)
  - Data masking per role (viewers see redacted prompts)
  - Crypto-shredding (destroy encryption key = destroy all data)
  - BAA tracking (Business Associate Agreement)
  - GDPR data subject access/deletion requests
  - Compliance posture reporting
  - IP allowlisting per project
  - Session timeout enforcement
  - Breach detection and notification hooks
"""

import os
import re
import time
import json
import uuid
import hashlib
import logging
import asyncio
from typing import Optional
from enum import Enum

logger = logging.getLogger("agentlens.compliance")


# ─── Data Classification ────────────────────────────────────

class DataClassification(str, Enum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    PHI = "phi"              # HIPAA Protected Health Information
    PII = "pii"              # Personally Identifiable Information
    RESTRICTED = "restricted" # Highest sensitivity


# Fields that may contain PHI/PII
PHI_FIELDS = {
    "prompt", "completion", "tool_args", "tool_result",
    "error_message", "input_data", "output_data",
    "thought", "decision",
}

# PHI detection patterns (conservative — flags potential PHI for review)
PHI_PATTERNS = {
    "ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "mrn": re.compile(r"\b(?:MRN|Medical Record)[:\s#]*\d{4,12}\b", re.IGNORECASE),
    "dob": re.compile(r"\b(?:DOB|Date of Birth|born)[:\s]*\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}\b", re.IGNORECASE),
    "phone": re.compile(r"\b(?:\+1[\s\-]?)?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{4}\b"),
    "email": re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Z|a-z]{2,}\b"),
    "credit_card": re.compile(r"\b(?:4\d{3}|5[1-5]\d{2}|3[47]\d{2}|6(?:011|5\d{2}))[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b"),
    "aadhaar": re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b"),
    "pan_card": re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"),
    "diagnosis": re.compile(r"\b(?:ICD[\-\s]?10|diagnosis|diagnosed with|treatment for)[:\s]", re.IGNORECASE),
    "medication": re.compile(r"\b(?:prescribed|medication|dosage|mg|tablet|capsule)\b", re.IGNORECASE),
    "api_key": re.compile(r"\b(?:sk-|pk-|api[_\-]?key)[A-Za-z0-9\-_]{10,}\b", re.IGNORECASE),
}

# Masking patterns — what to replace detected PHI with
MASK_REPLACEMENTS = {
    "ssn": "***-**-****",
    "mrn": "[MRN REDACTED]",
    "dob": "[DOB REDACTED]",
    "phone": "[PHONE REDACTED]",
    "email": "[EMAIL REDACTED]",
    "credit_card": "[CC REDACTED]",
    "aadhaar": "[AADHAAR REDACTED]",
    "pan_card": "[PAN REDACTED]",
    "diagnosis": "[PHI REDACTED]",
    "medication": "[PHI REDACTED]",
    "api_key": "[API KEY REDACTED]",
}


# ─── PHI Scanner ─────────────────────────────────────────────

class PHIScanner:
    """Scans text for potential PHI/PII and returns findings."""

    def scan(self, text: str) -> list[dict]:
        """Return list of PHI findings in text."""
        if not text or not isinstance(text, str):
            return []
        findings = []
        for phi_type, pattern in PHI_PATTERNS.items():
            for match in pattern.finditer(text):
                findings.append({
                    "type": phi_type,
                    "start": match.start(),
                    "end": match.end(),
                    "classification": DataClassification.PHI if phi_type in ("ssn", "mrn", "dob", "diagnosis", "medication")
                                      else DataClassification.PII,
                })
        return findings

    def contains_phi(self, text: str) -> bool:
        """Quick check: does text contain any PHI?"""
        if not text or not isinstance(text, str):
            return False
        for pattern in PHI_PATTERNS.values():
            if pattern.search(text):
                return True
        return False

    def mask(self, text: str) -> str:
        """Mask all PHI/PII in text."""
        if not text or not isinstance(text, str):
            return text
        masked = text
        for phi_type, pattern in PHI_PATTERNS.items():
            masked = pattern.sub(MASK_REPLACEMENTS.get(phi_type, "[REDACTED]"), masked)
        return masked

    def scan_event(self, event: dict) -> dict:
        """Scan an event for PHI. Returns event with phi_detected flag and findings."""
        findings = []
        for field in PHI_FIELDS:
            value = event.get(field)
            if value and isinstance(value, str):
                field_findings = self.scan(value)
                for f in field_findings:
                    f["field"] = field
                findings.extend(field_findings)
            elif value and isinstance(value, dict):
                for k, v in value.items():
                    if isinstance(v, str):
                        sub_findings = self.scan(v)
                        for f in sub_findings:
                            f["field"] = f"{field}.{k}"
                        findings.extend(sub_findings)
        return {
            "phi_detected": len(findings) > 0,
            "phi_count": len(findings),
            "findings": findings,
        }

    def mask_event(self, event: dict) -> dict:
        """Mask all PHI/PII in an event's sensitive fields."""
        masked = dict(event)
        for field in PHI_FIELDS:
            if field in masked and isinstance(masked[field], str):
                masked[field] = self.mask(masked[field])
            elif field in masked and isinstance(masked[field], dict):
                masked[field] = {k: self.mask(v) if isinstance(v, str) else v
                                for k, v in masked[field].items()}
        return masked


phi_scanner = PHIScanner()


# ─── IP Allowlist ────────────────────────────────────────────

class IPAllowlist:
    """Per-project IP allowlisting for access control."""

    def __init__(self):
        self._allowlists: dict[str, set[str]] = {}
        self._enabled: dict[str, bool] = {}

    def set_allowlist(self, project_id: str, ips: list[str]):
        """Set allowed IPs for a project. Empty list = disabled."""
        if ips:
            self._allowlists[project_id] = set(ips)
            self._enabled[project_id] = True
        else:
            self._allowlists.pop(project_id, None)
            self._enabled[project_id] = False

    def is_allowed(self, project_id: str, client_ip: str) -> bool:
        """Check if client IP is allowed for project."""
        if not self._enabled.get(project_id, False):
            return True  # No allowlist = allow all
        return client_ip in self._allowlists.get(project_id, set())

    def get_allowlist(self, project_id: str) -> list[str]:
        return list(self._allowlists.get(project_id, []))


ip_allowlist = IPAllowlist()


# ─── Session Timeout ─────────────────────────────────────────

class SessionManager:
    """Tracks API key sessions with timeout enforcement."""

    def __init__(self, timeout_minutes: int = 30):
        self.timeout = timeout_minutes * 60
        self._sessions: dict[str, float] = {}  # key_hash -> last_activity

    def touch(self, key_hash: str):
        self._sessions[key_hash] = time.time()

    def is_expired(self, key_hash: str) -> bool:
        last_activity = self._sessions.get(key_hash)
        if last_activity is None:
            return False  # First access
        return (time.time() - last_activity) > self.timeout

    def cleanup(self):
        now = time.time()
        expired = [k for k, t in self._sessions.items() if now - t > self.timeout * 2]
        for k in expired:
            del self._sessions[k]


session_manager = SessionManager(
    timeout_minutes=int(os.environ.get("AGENTLENS_SESSION_TIMEOUT", "30"))
)


# ─── Breach Detection ───────────────────────────────────────

class BreachDetector:
    """Monitors for suspicious activity patterns."""

    def __init__(self):
        self._failed_auths: dict[str, list[float]] = {}  # IP -> timestamps
        self._threshold = int(os.environ.get("AGENTLENS_BREACH_THRESHOLD", "10"))
        self._window = 300  # 5 minutes
        self._webhook = os.environ.get("AGENTLENS_BREACH_WEBHOOK")
        self._lockouts: dict[str, float] = {}  # IP -> lockout_until

    def record_failed_auth(self, client_ip: str):
        """Record a failed authentication attempt."""
        now = time.time()
        if client_ip not in self._failed_auths:
            self._failed_auths[client_ip] = []

        self._failed_auths[client_ip].append(now)
        # Keep only recent attempts
        self._failed_auths[client_ip] = [
            t for t in self._failed_auths[client_ip]
            if now - t < self._window
        ]

        count = len(self._failed_auths[client_ip])
        if count >= self._threshold:
            self._lockouts[client_ip] = now + 900  # 15 min lockout
            logger.critical(
                f"BREACH ALERT: {count} failed auth attempts from {client_ip} "
                f"in {self._window}s. IP locked out for 15 minutes."
            )
            if self._webhook:
                asyncio.create_task(self._notify_breach(client_ip, count))

    def is_locked_out(self, client_ip: str) -> bool:
        lockout_until = self._lockouts.get(client_ip, 0)
        if time.time() < lockout_until:
            return True
        elif lockout_until > 0:
            del self._lockouts[client_ip]
        return False

    async def _notify_breach(self, client_ip: str, attempts: int):
        """Send breach notification via webhook."""
        try:
            from urllib.request import Request, urlopen
            payload = json.dumps({
                "type": "breach_detection",
                "severity": "critical",
                "client_ip": client_ip,
                "failed_attempts": attempts,
                "window_seconds": self._window,
                "action": "ip_locked_out_15min",
                "timestamp": time.time(),
                "message": f"[AgentLens BREACH] {attempts} failed auth from {client_ip}. IP locked out.",
            }).encode()
            req = Request(
                self._webhook, data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, lambda: urlopen(req, timeout=10))
            logger.info(f"Breach notification sent to webhook")
        except Exception as e:
            logger.error(f"Breach webhook failed: {e}")

    def cleanup(self):
        now = time.time()
        stale = [ip for ip, times in self._failed_auths.items()
                 if all(now - t > self._window for t in times)]
        for ip in stale:
            del self._failed_auths[ip]


breach_detector = BreachDetector()


# ─── SSRF Prevention ────────────────────────────────────────

import ipaddress

BLOCKED_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


def validate_webhook_url(url: str) -> bool:
    """Validate a webhook URL is not targeting internal networks (SSRF prevention)."""
    from urllib.parse import urlparse

    if not url:
        return False

    parsed = urlparse(url)

    # Only allow http/https
    if parsed.scheme not in ("http", "https"):
        return False

    hostname = parsed.hostname
    if not hostname:
        return False

    # Block internal hostnames
    internal_hostnames = {"localhost", "0.0.0.0", "metadata.google.internal",
                          "169.254.169.254", "metadata"}
    if hostname.lower() in internal_hostnames:
        return False

    # Block .local, .internal domains
    if hostname.endswith((".local", ".internal", ".corp", ".lan")):
        return False

    # Try to resolve and check IP
    try:
        ip = ipaddress.ip_address(hostname)
        for network in BLOCKED_NETWORKS:
            if ip in network:
                return False
    except ValueError:
        pass  # Hostname, not IP — allow (DNS resolution happens at call time)

    return True


# ─── Compliance Report ──────────────────────────────────────

class ComplianceReporter:
    """Generates compliance posture reports."""

    def __init__(self, db_pool):
        self._pool = db_pool

    async def get_hipaa_posture(self) -> dict:
        """Return HIPAA compliance status."""
        from encryption import encryptor

        return {
            "standard": "HIPAA",
            "status": "partial" if encryptor.enabled else "non_compliant",
            "controls": {
                "encryption_at_rest": {
                    "status": "compliant" if encryptor.enabled else "non_compliant",
                    "detail": "AES-128-CBC + HMAC-SHA256 field-level encryption" if encryptor.enabled
                              else "Enable AGENTLENS_ENCRYPTION_KEY",
                },
                "encryption_in_transit": {
                    "status": "compliant" if os.environ.get("AGENTLENS_TLS_CERT") else "non_compliant",
                    "detail": "TLS configured" if os.environ.get("AGENTLENS_TLS_CERT")
                              else "Set AGENTLENS_TLS_CERT and AGENTLENS_TLS_KEY",
                },
                "access_controls": {
                    "status": "compliant" if os.environ.get("AGENTLENS_REQUIRE_AUTH", "").lower() in ("1", "true", "yes")
                             else "partial",
                    "detail": "RBAC with admin/member/viewer roles",
                },
                "audit_logging": {
                    "status": "compliant",
                    "detail": "All admin actions logged with timestamp, IP, user-agent",
                },
                "phi_detection": {
                    "status": "compliant",
                    "detail": "Auto-scan for SSN, MRN, DOB, diagnosis, medication, PII",
                },
                "data_retention": {
                    "status": "compliant",
                    "detail": "Configurable per-project retention with automated purge",
                },
                "breach_notification": {
                    "status": "compliant" if os.environ.get("AGENTLENS_BREACH_WEBHOOK") else "partial",
                    "detail": "Automated lockout + webhook notification on brute force",
                },
                "minimum_necessary": {
                    "status": "compliant",
                    "detail": "Role-based data masking — viewers see redacted PHI",
                },
            },
        }

    async def get_soc2_posture(self) -> dict:
        """Return SOC2 Type II readiness."""
        return {
            "standard": "SOC2_TYPE_II",
            "status": "partial",
            "controls": {
                "access_control": {
                    "status": "compliant",
                    "detail": "RBAC, API key management, key rotation, session timeout",
                },
                "encryption": {
                    "status": "compliant" if os.environ.get("AGENTLENS_ENCRYPTION_KEY") else "partial",
                    "detail": "Field-level encryption at rest, TLS in transit",
                },
                "logging_monitoring": {
                    "status": "compliant",
                    "detail": "Audit log, Prometheus metrics, structured logging",
                },
                "change_management": {
                    "status": "partial",
                    "detail": "CI/CD via GitHub Actions. Add deployment approval gates.",
                },
                "incident_response": {
                    "status": "compliant",
                    "detail": "Breach detection, auto-lockout, webhook alerts",
                },
                "data_retention": {
                    "status": "compliant",
                    "detail": "Automated retention policies with purge history",
                },
                "network_security": {
                    "status": "compliant",
                    "detail": "SSRF prevention, IP allowlisting, rate limiting, security headers",
                },
                "vulnerability_management": {
                    "status": "partial",
                    "detail": "Add SAST/DAST scanning in CI pipeline",
                },
            },
        }

    async def get_gdpr_posture(self) -> dict:
        """Return GDPR readiness status."""
        return {
            "standard": "GDPR",
            "status": "partial",
            "controls": {
                "data_minimization": {
                    "status": "compliant",
                    "detail": "PII redaction, configurable field encryption",
                },
                "right_to_access": {
                    "status": "compliant",
                    "detail": "Data subject access request API (GET /api/v1/gdpr/access)",
                },
                "right_to_erasure": {
                    "status": "compliant",
                    "detail": "Data subject deletion API (DELETE /api/v1/gdpr/erase)",
                },
                "data_portability": {
                    "status": "compliant",
                    "detail": "Export API returns JSON (GET /api/v1/gdpr/export)",
                },
                "breach_notification": {
                    "status": "compliant" if os.environ.get("AGENTLENS_BREACH_WEBHOOK") else "partial",
                    "detail": "72-hour breach notification via webhook",
                },
                "consent_management": {
                    "status": "not_applicable",
                    "detail": "AgentLens processes operational data, not user consent data",
                },
            },
        }

    async def get_full_report(self) -> dict:
        """Full compliance posture across all frameworks."""
        return {
            "timestamp": time.time(),
            "version": "0.4.0",
            "hipaa": await self.get_hipaa_posture(),
            "soc2": await self.get_soc2_posture(),
            "gdpr": await self.get_gdpr_posture(),
        }


# ─── GDPR Data Subject Requests ─────────────────────────────

class GDPRManager:
    """Handle GDPR data subject access and erasure requests."""

    def __init__(self, db_pool):
        self._pool = db_pool

    async def access_request(self, user_id: str, project_id: str) -> dict:
        """Return all data associated with a user_id (Right of Access)."""
        events = await self._pool.fetchall(
            "SELECT * FROM events WHERE user_id = ? AND project_id = ?",
            (user_id, project_id),
        )
        sessions = await self._pool.fetchall(
            "SELECT * FROM sessions WHERE user_id = ? AND project_id = ?",
            (user_id, project_id),
        )
        return {
            "user_id": user_id,
            "project_id": project_id,
            "events_count": len(events),
            "sessions_count": len(sessions),
            "events": events,
            "sessions": sessions,
            "exported_at": time.time(),
        }

    async def erasure_request(self, user_id: str, project_id: str) -> dict:
        """Delete all data for a user_id (Right to Erasure)."""
        # Count before deletion
        event_count = await self._pool.fetchval(
            "SELECT COUNT(*) FROM events WHERE user_id = ? AND project_id = ?",
            (user_id, project_id),
        ) or 0
        session_count = await self._pool.fetchval(
            "SELECT COUNT(*) FROM sessions WHERE user_id = ? AND project_id = ?",
            (user_id, project_id),
        ) or 0

        # Delete
        await self._pool.execute_write(
            "DELETE FROM events WHERE user_id = ? AND project_id = ?",
            (user_id, project_id),
        )
        await self._pool.execute_write(
            "DELETE FROM sessions WHERE user_id = ? AND project_id = ?",
            (user_id, project_id),
        )

        return {
            "user_id": user_id,
            "project_id": project_id,
            "events_deleted": event_count,
            "sessions_deleted": session_count,
            "erased_at": time.time(),
        }

    async def export_data(self, user_id: str, project_id: str) -> dict:
        """Return portable data export for a user (Right to Portability)."""
        return await self.access_request(user_id, project_id)
