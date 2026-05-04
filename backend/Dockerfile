FROM python:3.12-slim AS builder

WORKDIR /build

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ─── Production Image ─────────────────────────────────────
FROM python:3.12-slim

# Security: don't run as root
RUN groupadd -r agentlens && useradd -r -g agentlens -d /app -s /sbin/nologin agentlens

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

COPY . .

RUN mkdir -p /app/data && chown -R agentlens:agentlens /app

# Drop to non-root user
USER agentlens

EXPOSE 8340

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8340/api/health')" || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8340"]
