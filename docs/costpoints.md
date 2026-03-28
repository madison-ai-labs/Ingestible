# Cost Controls & Rate Limiting

This document maps every cost vector in Ingestible and the controls in place to prevent runaway spending.

## Cost Vectors

| Vector | Provider | When Triggered | Control |
|--------|----------|----------------|---------|
| LLM enrichment | Anthropic / OpenAI / Gemini / Ollama | `ingest add` (without `--skip-enrichment`) | Per-document token budget, per-document cost cap |
| LLM judge eval | Same | `ingest eval --judge`, `POST /eval/judge` | Concurrency limit (`llm_judge_concurrency`) |
| HyDE query expansion | Same | Search with `--hyde` or `hyde: true` | LRU cache (200 entries, 5min TTL) |
| Sub-question decomposition | Same | Search with sub-questions enabled | `max_sub_questions` cap (default: 3) |
| Knowledge graph extraction | Same | Enrichment with `extract_knowledge_graph=true` | Covered by per-document token budget |
| Embedding API | OpenAI / Cohere / Voyage | Ingestion (stage 5), search queries | Batching (500/batch). Local provider = free |
| Supabase DB | Supabase | Every API request (auth, usage tracking) | Cached key validation (60s TTL), cached quotas (30s TTL) |
| Storage (disk) | Fly.io volume / local | Ingestion (stage 6) | `max_upload_bytes`, `min_disk_space_mb` readiness check |
| Compute (Fly.io) | Fly.io | Always | Auto-stop machines, concurrency limits (soft 20, hard 25) |
| Compute (background jobs) | Fly.io / local | `POST /ingest/async` | Global worker cap, per-user concurrency limit |

## Enforcement Layers

### Layer 1: Tier Limits (Supabase → API)

Tier limits are stored in the `tier_limits` Supabase table and enforced in the API middleware.

| Limit | Free | Premium | Admin | Enforced In |
|-------|------|---------|-------|-------------|
| `requests_per_day` | 100 | 10,000 | 999,999 | `AuthMiddleware` — returns 429 when exceeded |
| `requests_per_minute` | 10 | 100 | 9,999 | SlowAPI rate limiter (per-IP) |
| `max_documents` | 5 | 100 | 999,999 | `_check_ingestion_quotas()` — returns 403 |
| `max_file_size_mb` | 50 | 500 | 999 | `_check_ingestion_quotas()` — returns 413 |
| `enrichment_enabled` | false | true | true | `_check_ingestion_quotas()` — forces `skip_enrichment=True` |

Quota data is fetched from Supabase via `get_user_quotas()` in `auth.py` with a **30-second cache**. If Supabase is unreachable, requests are allowed through (fail-open to avoid blocking on quota service outage).

Users authenticated via env-var keys (`INGEST_API_KEYS`) bypass tier limits entirely — they are trusted operator keys.

### Layer 2: Per-Document LLM Budget

Prevents a single large document from running up unbounded LLM costs.

| Setting | Default | Env Var |
|---------|---------|---------|
| `max_llm_tokens_per_document` | 1,000,000 | `INGEST_MAX_LLM_TOKENS_PER_DOCUMENT` |
| `max_llm_cost_per_document` | $5.00 | `INGEST_MAX_LLM_COST_PER_DOCUMENT` |

**How it works:**
- Every LLM call during enrichment records token usage via `record_llm_usage()` in `models/costs.py`
- After each LLM call, `check_budget()` compares cumulative tokens and estimated USD cost against the caps
- If either cap is exceeded, `TokenBudgetExceeded` is raised
- The enrichment stops gracefully — partially enriched chunks are kept, the document is still stored
- A warning is logged: "Token budget exceeded — stopping enrichment at N tokens ($X.XX)"

**Cost estimation** uses provider-specific rates:
- Anthropic Claude Haiku: $0.25/1M input, $1.25/1M output
- OpenAI GPT-4o-mini: $0.15/1M input, $0.60/1M output
- Gemini 2.0 Flash: $0.10/1M input, $0.40/1M output
- Ollama: $0 (local)

### Layer 3: Concurrency Limits

| Setting | Default | Scope | Env Var |
|---------|---------|-------|---------|
| `max_concurrent_ingestions` | 2 | Global (all users) | `INGEST_MAX_CONCURRENT_INGESTIONS` |
| `max_jobs_per_user` | 1 | Per user | `INGEST_MAX_JOBS_PER_USER` |
| `llm_concurrency` | 10 | Per ingestion stage | `INGEST_LLM_CONCURRENCY` |
| `max_total_llm_concurrency` | 20 | Global (batch mode) | `INGEST_MAX_TOTAL_LLM_CONCURRENCY` |
| `llm_judge_concurrency` | 5 | LLM-as-judge eval | `INGEST_LLM_JUDGE_CONCURRENCY` |

**Per-user concurrency** is tracked in `TaskQueue._user_jobs` (dict keyed by user identifier, protected by threading.Lock). When a user exceeds their limit, `POST /ingest/async` returns 429 "Too many concurrent ingestions."

### Layer 4: API Rate Limiting (SlowAPI)

Applied per-IP via the `@limiter.limit()` decorator on every endpoint.

| Endpoint Group | Default Rate | Env Var |
|----------------|-------------|---------|
| Ingestion (`/ingest/*`) | 10/minute | `INGEST_RATE_LIMIT_INGEST` |
| Search (`/search`, `*/search`) | 60/minute | `INGEST_RATE_LIMIT_SEARCH` |
| Everything else | 120/minute | `INGEST_RATE_LIMIT_DEFAULT` |

Returns `429 Too Many Requests` with `Retry-After` header.

### Layer 5: LLM Call Resilience

| Setting | Default | Purpose |
|---------|---------|---------|
| `llm_timeout` | 120s | Per-call timeout — prevents hanging connections |
| `llm_max_retries` | 3 | Max retry attempts on transient errors (429, 500, 502, 503) |
| `llm_retry_base_delay` | 1.0s | Exponential backoff: 1s → 2s → 4s → fail |

Only transient HTTP errors are retried. 400-level errors (bad request, auth) fail immediately.

### Layer 6: Query-Time Caching

| Feature | Cache | TTL | Max Size |
|---------|-------|-----|----------|
| HyDE query expansion | In-memory dict | 5 minutes | 200 entries |
| Supabase key validation | In-memory dict | 60 seconds | Unbounded (keys are small) |
| User quotas | In-memory dict | 30 seconds | Unbounded (one entry per active key) |
| Document searchers | LRU cache | Session | `searcher_cache_size` (default: 50) |

### Layer 7: Upload & Storage Limits

| Setting | Default | Env Var |
|---------|---------|---------|
| `max_upload_bytes` | 500 MB | `INGEST_MAX_UPLOAD_BYTES` |
| `min_disk_space_mb` | 500 MB | `INGEST_MIN_DISK_SPACE_MB` |
| `parse_timeout` | 300s (5 min) | `INGEST_PARSE_TIMEOUT` |

The readiness endpoint (`GET /health/ready`) checks disk space. If free space drops below `min_disk_space_mb`, the check returns `"degraded"`.

### Layer 8: User Suspension

Admin can suspend users via the admin dashboard or `PATCH /api/admin/users/{id}` with `{ suspended: true }`. Suspended users receive `403 Account suspended` on all authenticated requests.

## Fly.io Deployment Controls

Configured in `fly.toml`:

| Setting | Value | Purpose |
|---------|-------|---------|
| VM size | `shared-cpu-1x`, 2GB RAM | Limits compute cost |
| Concurrency | Soft 20, hard 25 | Limits concurrent connections |
| Auto-stop | Enabled | Machines stop when idle (no cost at zero traffic) |
| Min machines | 0 | No always-on cost |
| Health check | `GET /health` every 30s | Detects unhealthy instances |
| Persistent volume | 10 GB | Bounded storage |

## Worst-Case Cost Scenarios

### Scenario 1: Large document ingestion (1000 pages)
- ~5000 L3 chunks
- Enrichment: ~1M tokens → **capped at `max_llm_tokens_per_document` (1M) or `max_llm_cost_per_document` ($5)**
- Embeddings (local): $0
- Embeddings (OpenAI): ~$0.80
- **Total: $0-5.80 per document** (hard capped)

### Scenario 2: Search abuse (100 searches/minute)
- Rate limited to 60/min by SlowAPI
- With HyDE: 60 LLM calls/min → cached after first call for identical queries
- Without HyDE: $0 per search (no LLM calls)
- **Total: $0-0.60/min** (rate limited + cached)

### Scenario 3: Free tier user trying to exceed limits
- 5 document cap enforced → 403 on 6th ingestion
- Enrichment disabled → no LLM cost
- 100 requests/day cap → 429 after 100
- 50 MB file size → 413 on larger files
- **Total: $0** (all gated)

## Missing Controls (Known Gaps)

These are documented for future implementation:

1. **No per-user storage quota** — users can't exceed document count, but storage per document is unbounded
2. **No request log retention policy** — `api_request_log` table grows unbounded in Supabase
3. **No embedding API rate limiting** — relies on provider-side rate limits
4. **Daily quota reset** — `requests_per_day` check uses today's `api_key_usage` rows, but no explicit reset job (rows accumulate naturally by date)
5. **Job queue depth** — no cap on queued (pending) jobs, only on concurrent workers
