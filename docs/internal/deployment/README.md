# Deployment Guide

Ingestible runs as a Docker container on **Fly.io** with **Supabase** (pgvector) as the production vector backend. For self-hosted deployments as part of CognitiveVault, see the [unified Docker Compose stack](https://github.com/SimplyLiz/cognitive-vault/blob/develop/docs/deployment.md). Local development uses ChromaDB with no external dependencies.

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Local Development (Docker)](#local-development-docker)
- [Production Deployment (Fly.io + Supabase)](#production-deployment-flyio--supabase)
- [API Key Management](#api-key-management)
- [Environment Variables Reference](#environment-variables-reference)
- [CI/CD Pipeline](#cicd-pipeline)
- [Troubleshooting](#troubleshooting)

---

## Architecture Overview

```
┌─────────────┐       ┌──────────────────────────┐       ┌──────────────────┐
│   Client     │──────▶│  Fly.io (Docker)          │──────▶│  Supabase        │
│              │ HTTPS │  ingestible-api           │  TCP  │  PostgreSQL +    │
│              │       │  gunicorn + uvicorn        │       │  pgvector        │
│              │       │  /data (volume)            │       │                  │
└─────────────┘       └──────────────────────────┘       └──────────────────┘
```

**Local dev** replaces the entire right side with a single Docker container using file-based ChromaDB.

| Component | Local | Production |
|-----------|-------|------------|
| Vector backend | ChromaDB (file) | Supabase pgvector |
| Document storage | `data/` (local) | Fly.io volume (`/data`) |
| Embedding model | E5-large-v2 (in-container) | E5-large-v2 (in-container) |
| Domain | `localhost:8081` | `ingestible-api.fly.dev` |

---

## Local Development (Docker)

### Quick start

```bash
# Build and run with ChromaDB (no external deps)
docker compose up --build

# API available at http://localhost:8081
curl http://localhost:8081/health
```

### With API key auth

```bash
# Create a .env file
echo 'INGEST_API_KEYS=my-local-dev-key' >> .env

# Rebuild
docker compose up --build

# Requests now require a bearer token
curl -H "Authorization: Bearer my-local-dev-key" http://localhost:8081/documents
```

### Build args

The Dockerfile accepts an `EXTRAS` build arg controlling which optional dependencies are installed:

| Value | Installs | Use case |
|-------|----------|----------|
| `pgvector,gemini` | pgvector + Gemini SDK (~500MB) | Thin API server (cloud embeddings) |
| `local,pgvector,gemini` | + sentence-transformers + PyTorch (~3GB) | Full ingestion worker (local embeddings) |

---

## Production Deployment (Fly.io + Supabase)

### Prerequisites

- [Fly CLI](https://fly.io/docs/flyctl/install/) (`brew install flyctl`)
- [Supabase CLI](https://supabase.com/docs/guides/cli) (`brew install supabase/tap/supabase`)
- Logged in to both: `fly auth login` and `supabase login`

### Initial setup

```bash
# 1. Link Supabase project
supabase link --project-ref <your-project-ref>

# 2. Enable pgvector extension
supabase db push

# 3. Create Fly app
fly launch --no-deploy

# 4. Create persistent volume for document storage
fly volumes create ingestible_data --size 10 --region fra

# 5. Set secrets
fly secrets set \
  INGEST_PGVECTOR_URL="postgresql://postgres.<ref>:<password>@aws-0-eu-central-1.pooler.supabase.com:6543/postgres" \
  INGEST_VECTOR_BACKEND=pgvector \
  INGEST_API_KEYS="$(openssl rand -base64 32)" \
  INGEST_LLM_PROVIDER=gemini \
  INGEST_GEMINI_API_KEY="AIzaSy..." \
  INGEST_DATA_DIR=/data \
  INGEST_LOG_JSON=true

# 6. Deploy
fly deploy
```

### Checking deployment

```bash
# Status
fly status

# Tail logs
fly logs

# Health check
curl https://ingestible-api.fly.dev/health

# Deep readiness (checks data dir, disk space)
curl https://ingestible-api.fly.dev/health/ready
```

---

## API Key Management

### How auth works

The API uses Bearer token authentication via the `INGEST_API_KEYS` environment variable.

- Keys are comma-separated: `INGEST_API_KEYS=key1,key2,key3`
- If `INGEST_API_KEYS` is empty or unset, **auth is disabled** (open access)
- Tokens are compared using constant-time HMAC comparison (timing-attack safe)
- Public endpoints that skip auth: `/health`, `/health/ready`, `/docs`, `/openapi.json`, `/redoc`, `/metrics`

### Generating API keys

```bash
# Generate a cryptographically secure key
openssl rand -base64 32

# Or using Python
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

### Adding keys to production

```bash
# Set a single key
fly secrets set INGEST_API_KEYS="$(openssl rand -base64 32)"

# Set multiple keys (e.g., one per consumer)
fly secrets set INGEST_API_KEYS="key-for-frontend,key-for-worker,key-for-admin"
```

### Using the API key

```bash
# All authenticated endpoints require the Authorization header
curl -H "Authorization: Bearer <your-key>" \
  https://ingestible-api.fly.dev/documents

# Upload a document
curl -X POST \
  -H "Authorization: Bearer <your-key>" \
  -F "file=@document.pdf" \
  https://ingestible-api.fly.dev/ingest

# Search
curl -H "Authorization: Bearer <your-key>" \
  "https://ingestible-api.fly.dev/documents/<doc_id>/search?q=your+query"
```

### Rotating keys

1. Generate a new key
2. Add the new key alongside the old one: `fly secrets set INGEST_API_KEYS=old-key,new-key`
3. Update all consumers to use the new key
4. Remove the old key: `fly secrets set INGEST_API_KEYS=new-key`

---

## Environment Variables Reference

All variables use the `INGEST_` prefix. Set via `fly secrets set` for production or in `.env` for local.

### Required for production

| Variable | Description | Example |
|----------|-------------|---------|
| `INGEST_VECTOR_BACKEND` | Vector store backend | `pgvector` |
| `INGEST_PGVECTOR_URL` | Supabase PostgreSQL connection string | `postgresql://postgres.ref:pass@pooler.supabase.com:6543/postgres` |
| `INGEST_API_KEYS` | Comma-separated Bearer tokens | `key1,key2` |
| `INGEST_LLM_PROVIDER` | LLM provider | `gemini`, `anthropic`, `openai`, or `ollama` |
| `INGEST_GEMINI_API_KEY` | Gemini API key | `AIzaSy...` |

### Optional

| Variable | Default | Description |
|----------|---------|-------------|
| `INGEST_LLM_PROVIDER` | `anthropic` | LLM provider (`anthropic`, `openai`, `gemini`, or `ollama`) |
| `INGEST_OPENAI_API_KEY` | — | OpenAI key (if using openai provider) |
| `INGEST_ANTHROPIC_API_KEY` | — | Anthropic key (if using anthropic provider) |
| `INGEST_GEMINI_API_KEY` | — | Gemini key (if using gemini provider) |
| `INGEST_GEMINI_MODEL` | `gemini-2.0-flash` | Gemini model name |
| `INGEST_OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server URL |
| `INGEST_OLLAMA_MODEL` | `llama3.1` | Ollama model name |
| `INGEST_DATA_DIR` | `data` | Document storage path |
| `INGEST_LOG_JSON` | `true` | JSON structured logging |
| `INGEST_CORS_ORIGINS` | `["*"]` | Allowed CORS origins |
| `INGEST_RATE_LIMIT_INGEST` | `10/minute` | Ingestion rate limit |
| `INGEST_RATE_LIMIT_SEARCH` | `60/minute` | Search rate limit |
| `INGEST_MAX_UPLOAD_BYTES` | `500000000` | Max upload size (500MB) |
| `INGEST_EMBEDDING_PROVIDER` | `local` | Embedding provider |
| `INGEST_HYDE_ENABLED` | `false` | HyDE query expansion |
| `INGEST_KG_RETRIEVAL_ENABLED` | `false` | Knowledge graph retrieval boost |
| `INGEST_AUTO_MERGE_ENABLED` | `false` | Auto-merge retrieval |

Full list in `src/ingestible/config.py` — every field on the `Settings` class maps to `INGEST_<FIELD_NAME>`.

---

## CI/CD Pipeline

### Flow

```
tag v1.x.x on main
  → CI (lint, test, import check, security scan)
  → Build Python wheel + publish to PyPI
  → Build Docker image + push to ghcr.io
  → Deploy to Fly.io
```

### Workflow files

| File | Trigger | What it does |
|------|---------|--------------|
| `.github/workflows/ci.yml` | Push/PR to main, develop | Lint, test (3.11/3.12/3.13), import check, security scan |
| `.github/workflows/merge-to-main.yml` | PR to main | Docker build smoke test |
| `.github/workflows/release.yml` | Tag `v*` | Full release: PyPI + ghcr.io + GitHub Release + Fly.io deploy |

### GitHub Secrets required

| Secret | Where to set | How to get |
|--------|-------------|------------|
| `FLY_API_TOKEN` | Repo → Settings → Environments → `production` → Secrets | `fly tokens create deploy -x 999999h` |

PyPI publishing uses trusted publishers (OIDC), no secret needed.

### Triggering a release

```bash
# 1. Bump version in pyproject.toml
# 2. Commit and merge to main
# 3. Tag and push
git tag v1.1.0
git push origin v1.1.0
# → CI runs → Docker builds → Fly.io deploys automatically
```

### Manual deploy

```bash
fly deploy
```

---

## Troubleshooting

### Build fails on Fly.io

```bash
# Check build logs
fly logs

# Common cause: memory limit exceeded (torch is large)
# Fix: scale the VM or use the thin image (EXTRAS="pgvector,gemini")
fly scale memory 2048
```

### Container starts but health check fails

```bash
# Check if the volume is mounted
fly ssh console -C "ls -la /data"

# Check readiness endpoint for specific failures
curl https://ingestible-api.fly.dev/health/ready
```

### pgvector connection refused

```bash
# Verify the secret is set
fly secrets list

# Test from local machine
psql "<your-pgvector-url>" -c "SELECT 1;"

# Check Supabase is not paused
supabase projects list
```

### "No API keys configured" warning in logs

This means `INGEST_API_KEYS` is not set — the API is running without authentication. Set it:

```bash
fly secrets set INGEST_API_KEYS="$(openssl rand -base64 32)"
```

### Switching back to ChromaDB

If Supabase is down or you need to fall back:

```bash
fly secrets set INGEST_VECTOR_BACKEND=chroma
# ChromaDB will use /data on the volume
```
