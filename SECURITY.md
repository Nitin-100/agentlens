# AgentLens Security Policy

## Reporting Vulnerabilities

If you discover a security vulnerability, please report it responsibly:

- **Email**: security@agentlens.dev
- **Do NOT** open a public GitHub issue for security vulnerabilities.
- We will acknowledge receipt within 48 hours.
- We aim to provide a fix within 7 days for critical issues.

## Security Architecture

### Authentication & Authorization
- **RBAC**: Three roles (admin, member, viewer) with permission matrix
- **API Key Security**: HMAC-SHA256 hashed (keyed, not plain SHA-256), never stored in plaintext
- **Auth Required by Default**: `AGENTLENS_REQUIRE_AUTH=true` is the default. No-auth falls back to viewer (read-only), not admin.
- **Key Rotation**: Zero-downtime key rotation with configurable grace periods
- **Session Timeout**: Configurable (default 30 min)

### Encryption
- **At Rest**: AES-128-CBC + HMAC-SHA256 (Fernet) field-level encryption for all sensitive fields
- **In Transit**: TLS 1.2+ support (configure via `AGENTLENS_TLS_CERT` / `AGENTLENS_TLS_KEY`)
- **Fail-Closed**: If encryption fails, the system rejects the data rather than storing plaintext
- **Key Rotation**: Supports encryption key rotation with multi-key decryption during grace period

### Network Security
- **CORS**: Locked down by default (no wildcard). Must explicitly configure `AGENTLENS_CORS_ORIGINS`.
- **Rate Limiting**: Token bucket (100 req/s, burst 500) per IP/key
- **SSRF Protection**: Webhook URLs validated against private/internal networks
- **Security Headers**: X-Frame-Options, CSP, HSTS, X-Content-Type-Options, Referrer-Policy
- **IP Allowlisting**: Per-project IP restrictions

### Threat Detection
- **Breach Detection**: Auto-lockout after repeated failed auth attempts (default: 10 in 5 min)
- **Webhook Alerts**: Configurable breach notification via `AGENTLENS_BREACH_WEBHOOK`
- **Audit Logging**: All admin actions logged with timestamp, IP, user-agent

### Data Protection
- **PHI/PII Detection**: Automatic scanning for SSN, MRN, DOB, diagnosis, medication, email, phone, credit cards, Aadhaar, PAN
- **Auto-Masking**: Role-based data masking (viewers see redacted PHI)
- **Data Retention**: Configurable per-project with automated background purge
- **GDPR**: Data subject access, erasure, and portability APIs

### Container Security
- **Non-Root**: Docker container runs as unprivileged `agentlens` user
- **Multi-Stage Build**: Minimized attack surface
- **Health Checks**: Built into Dockerfile and docker-compose
- **Resource Limits**: CPU and memory limits configured in docker-compose

## Compliance

| Framework | Status    | Key Controls |
|-----------|-----------|-------------|
| HIPAA     | Partial   | Encryption at rest, PHI detection, audit logs, access controls, breach notification |
| SOC2 II   | Partial   | RBAC, encryption, logging, incident response, data retention, network security |
| GDPR      | Compliant | Data access/erasure/export APIs, data minimization, breach notification |

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `AGENTLENS_REQUIRE_AUTH` | Require API key authentication | `true` |
| `AGENTLENS_CORS_ORIGINS` | Comma-separated allowed origins | `""` (same-origin only) |
| `AGENTLENS_ENCRYPTION_KEY` | Fernet key for encryption at rest | Auto-generated |
| `AGENTLENS_HMAC_SECRET` | Secret for API key hashing | Must set in production |
| `AGENTLENS_TLS_CERT` | TLS certificate path | None |
| `AGENTLENS_TLS_KEY` | TLS private key path | None |
| `AGENTLENS_BREACH_WEBHOOK` | Webhook URL for breach alerts | None |
| `AGENTLENS_BREACH_THRESHOLD` | Failed auths before lockout | `10` |
| `AGENTLENS_SESSION_TIMEOUT` | Session timeout (minutes) | `30` |
