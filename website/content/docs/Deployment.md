# Deployment

Ingestible runs as a FastAPI application behind gunicorn. There are several deployment options depending on your needs.

## Docker (recommended)

### Development

```bash
cp .env.example .env
# Edit .env with your API keys

docker compose up -d
```

This builds with the `local` extras (ChromaDB file-based storage, local embeddings) and exposes the API and web UI at `http://localhost:8081`.

### Production with pgvector

```bash
docker compose -f docker-compose.prod.yml up -d
```

**Required environment variables in `.env`:**

```
INGEST_PGVECTOR_URL=postgresql://user:pass@host:5432/ingestible
INGEST_API_KEYS=your-api-key-here
INGEST_ANTHROPIC_API_KEY=sk-ant-...
```

The production compose file uses the `local,pgvector` extras and sets `INGEST_VECTOR_BACKEND=pgvector`.

### Docker run (standalone)

```bash
docker run -d \
  -p 8081:8081 \
  -v ingestible-data:/app/data \
  --env-file .env \
  ghcr.io/simplyliz/ingestible:latest
```

Two image variants are published:
- `ghcr.io/simplyliz/ingestible:latest` — full image (~3GB) with all extras
- `ghcr.io/simplyliz/ingestible:latest-slim` — thin API image (~500MB)

### Custom Docker build

The Dockerfile supports a build argument to control which extras are installed:

```bash
docker build --build-arg EXTRAS="local,pgvector,gemini" -t ingestible .
```

## Fly.io

Ingestible includes a `fly.toml` for one-command deployment to Fly.io.

### Initial setup

```bash
fly launch --no-deploy
fly volumes create ingestible_data --region fra --size 10
```

### Set secrets

```bash
fly secrets set INGEST_API_KEYS=your-api-key
fly secrets set INGEST_GEMINI_API_KEY=your-gemini-key
# Or use your preferred LLM provider:
# fly secrets set INGEST_ANTHROPIC_API_KEY=sk-ant-...
# fly secrets set INGEST_OPENAI_API_KEY=sk-...
```

### Deploy

```bash
fly deploy
```

### Configuration

The included `fly.toml` configures:

| Setting | Value |
|---------|-------|
| Region | `fra` (Frankfurt) |
| VM | `shared-cpu-1x`, 2GB RAM |
| Port | 8081 (HTTPS enforced) |
| Health check | `GET /health` every 30s |
| Persistent volume | `/app/data` |
| Auto-stop | Machines stop when idle, start on request |
| Concurrency | Soft 20, hard 25 requests |
| Extras | `local,pgvector,gemini` |

### Scaling

For higher throughput, adjust workers via the `WEB_CONCURRENCY` environment variable:

```bash
fly secrets set WEB_CONCURRENCY=4
```

To upgrade the VM:

```bash
fly scale vm shared-cpu-2x --memory 4096
```

## Gunicorn Configuration

The `gunicorn.conf.py` included in the repository configures:

| Setting | Value | Notes |
|---------|-------|-------|
| Workers | `min(cpu_count * 2 + 1, 8)` | Override with `WEB_CONCURRENCY` |
| Worker class | `uvicorn.workers.UvicornWorker` | Async ASGI |
| Timeout | 600s (10 min) | Ingestion can be slow for large documents |
| Preload | `true` | Shares model memory across workers. Set `GUNICORN_PRELOAD=false` for low-memory environments |
| Max requests | 1000 + jitter | Workers restart periodically to prevent memory leaks |

## Direct (uvicorn)

For development or simple deployments:

```bash
ingest serve                            # default: localhost:8081
ingest serve --host 0.0.0.0 --port 9000
ingest serve --reload                   # auto-reload on code changes
```

For production without Docker:

```bash
gunicorn ingestible.api:app -c gunicorn.conf.py
```

## Health Checks

Two endpoints are available for orchestrators and load balancers:

- `GET /health` — fast liveness probe, returns `{"status": "ok"}`. No dependency checks.
- `GET /health/ready` — deep readiness check. Verifies data directory, disk space, embedding model, and LLM API. Returns `"ready"` or `"degraded"` with per-check details.

## Monitoring

Prometheus metrics are exposed at `GET /metrics`:

| Metric | Type | Description |
|--------|------|-------------|
| `ingestible_ingest_duration_seconds` | histogram | Ingestion latency by stage |
| `ingestible_active_ingestions` | gauge | Currently running ingestion jobs |
| `ingestible_llm_calls_total` | counter | LLM API calls by provider and status |
| `ingestible_search_duration_seconds` | histogram | Search query latency |

## Environment Variables

See the [Usage Guide](Usage) for the full configuration reference. Key production settings:

```
INGEST_API_KEYS=key1,key2               # API authentication (comma-separated)
INGEST_CORS_ORIGINS=https://app.example.com
INGEST_RATE_LIMIT_INGEST=10/minute
INGEST_RATE_LIMIT_SEARCH=60/minute
INGEST_LOG_JSON=true
INGEST_LOG_LEVEL=INFO
INGEST_MAX_UPLOAD_BYTES=500000000
INGEST_MAX_CONCURRENT_INGESTIONS=2
INGEST_AUDIT_ENABLED=true
```
