# syntax=docker/dockerfile:1

# ── Build stage ──────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

COPY pyproject.toml README.md ./
COPY src/ src/

RUN pip install --no-cache-dir build && \
    python -m build --wheel --outdir /build/dist

# ── Runtime stage ────────────────────────────────────────────
FROM python:3.12-slim

# Install ffmpeg for audio/video support
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# Non-root user
RUN groupadd -r ingestible && useradd -r -g ingestible -m ingestible

WORKDIR /app

# Install the wheel with local embedding support
COPY --from=builder /build/dist/*.whl /tmp/
RUN pip install --no-cache-dir "/tmp/ingestible-*.whl[local]" && \
    rm /tmp/*.whl

# Copy gunicorn config
COPY gunicorn.conf.py .

# Create data directory
RUN mkdir -p /app/data && chown -R ingestible:ingestible /app

USER ingestible

# Default environment
ENV INGEST_DATA_DIR=/app/data
ENV INGEST_LOG_JSON=true

EXPOSE 8081

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import httpx; r=httpx.get('http://localhost:8081/health'); r.raise_for_status()"

CMD ["gunicorn", "ingestible.api:app", "-c", "gunicorn.conf.py"]
