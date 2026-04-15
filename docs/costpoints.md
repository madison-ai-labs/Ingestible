# Cost Controls & Rate Limiting

This document maps every cost vector in Ingestible and the controls in place to prevent runaway spending.

Last updated: 2026-03-28

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

## LLM Provider Pricing (as of March 2026)

### Enrichment Models

| Provider | Model | Input / 1M tokens | Output / 1M tokens | Notes |
|----------|-------|-------------------|--------------------:|-------|
| Anthropic | Claude Haiku 4.5 | $1.00 | $5.00 | Default (`anthropic_model` in config) |
| Anthropic | Claude Sonnet 4.6 | $3.00 | $15.00 | |
| OpenAI | GPT-4o-mini | $0.15 | $0.60 | |
| Google | Gemini 2.5 Flash | $0.30 | $2.50 | Latest stable Flash model |
| Google | Gemini 2.0 Flash | $0.10 | $0.40 | **Deprecated — shuts down June 1, 2026** |
| Ollama | Any local model | $0 | $0 | Self-hosted only |

### Embedding Models

| Provider | Model | Cost / 1M tokens | Notes |
|----------|-------|------------------:|-------|
| OpenAI | text-embedding-3-small | $0.02 | **Recommended for cloud** |
| OpenAI | text-embedding-3-large | $0.13 | |
| OpenAI | text-embedding-3-small (batch) | $0.01 | 50% discount via batch API |
| Cohere | embed-english-v3.0 | $0.10 | |
| Voyage | voyage-3 | $0.06 | |
| Local | intfloat/e5-large-v2 | $0 | Requires PyTorch (~3GB RAM) |

### Cost per document ingested (typical 50-page doc, ~25K tokens)

| Step | Tokens | Gemini 2.5 Flash | Claude Haiku 4.5 | GPT-4o-mini |
|------|--------|----------------:|----------------:|------------:|
| Embedding (3 passes) | ~75K | $0.0015 | $0.0015 | $0.0015 |
| Enrichment input | ~50K | $0.015 | $0.050 | $0.008 |
| Enrichment output | ~15K | $0.038 | $0.075 | $0.009 |
| **Total per document** | | **$0.05** | **$0.13** | **$0.02** |

### Cost per search query

| Step | Tokens | Cost (OpenAI embed) |
|------|--------|--------------------:|
| Query embedding | ~50 | $0.000001 |
| HyDE expansion (if enabled) | ~500 in + ~200 out | $0.0002–0.001 |
| **Without HyDE** | | **~free** |

## Enforcement Layers

### Layer 1: Tier Limits (Supabase → API)

Tier limits are stored in the `tier_limits` Supabase table and enforced in the API middleware.

#### Cloud Tiers (website pricing page)

| Limit | Free | Pay As You Go | Starter (BYOK) | Pro | Business |
|-------|------|--------------|-----------------|-----|----------|
| Price | $0 | Usage-based | $9.99/mo | $19.99/mo | $29.99/mo |
| `documents_per_day` | 5 | Unlimited | 50 | 500 | Unlimited |
| `tokens_per_document` | 1,000 | 100,000 | 100,000 | 500,000 | 1,000,000 |
| `max_file_size_mb` | 50 | 200 | 200 | 500 | 1,000 |
| `api_keys` | 0 | 1 | 3 | 5 | 10 |
| `requests_per_day` | — | 1,000 | 5,000 | 20,000 | 50,000 |
| `requests_per_minute` | 10 | 30 | 60 | 120 | 200 |
| `enrichment` | No | Basic | Full (BYOK) | Full (included) | Full (included) |
| `persistent_storage` | No | No | No | No | Yes |
| `search_enhancements` | No | No | No | All | All |

#### Enterprise / On-Premise

| | Self-Hosted License | Enterprise SLA |
|---|---|---|
| Price | $2,499 one-time | $499/mo (annual) |
| Usage limits | None | None |
| Updates | 1 year included | Continuous |
| Support | Community | Dedicated (48h response) |
| Compliance | — | SOC2, HIPAA on request |

#### Supabase enforcement (database tier_limits table)

| Limit | Free | Premium | Admin | Enforced In |
|-------|------|---------|-------|-------------|
| `requests_per_day` | 100 | 10,000 | 999,999 | `AuthMiddleware` — returns 429 when exceeded |
| `requests_per_minute` | 10 | 100 | 9,999 | SlowAPI rate limiter (per-IP) |
| `max_documents` | 5 | 100 | 999,999 | `_check_ingestion_quotas()` — returns 403 |
| `max_file_size_mb` | 50 | 500 | 999 | `_check_ingestion_quotas()` — returns 413 |
| `enrichment_enabled` | false | true | true | `_check_ingestion_quotas()` — forces `skip_enrichment=True` |

> **Note:** The Supabase tier_limits table needs to be updated to match the new 5-tier cloud structure. The current Free/Premium/Admin tiers in the database predate the pricing page.

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

**Cost estimation** uses provider-specific rates (keep these in sync with `models/costs.py`):

| Provider | Model | Input rate | Output rate |
|----------|-------|-----------|------------|
| Anthropic | Claude Haiku 4.5 | $1.00/1M | $5.00/1M |
| OpenAI | GPT-4o-mini | $0.15/1M | $0.60/1M |
| Google | Gemini 2.5 Flash | $0.30/1M | $2.50/1M |
| Ollama | Any | $0 | $0 |

> **Action required:** Verify `models/costs.py` reflects these rates. The previous rates ($0.25/$1.25 for Haiku, $0.10/$0.40 for Gemini) are outdated — Claude 3 Haiku is deprecated April 2026, Gemini 2.0 Flash is deprecated June 2026.

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
| Document searchers | LRU cache | Session | `searcher_cache_size` (default: 10) |

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
| VM size | `shared-cpu-1x`, 512MB RAM | Cloud image (no PyTorch) |
| Docker extras | `pgvector,gemini` | No `local` — uses API-based embeddings |
| Embedding provider | `openai` (text-embedding-3-small) | ~$0.02/1M tokens, 0 RAM |
| Searcher cache | 10 | ~50-145MB per cached doc |
| Concurrency | Soft 20, hard 25 | Limits concurrent connections |
| Auto-stop | Enabled | Machines stop when idle (no cost at zero traffic) |
| Min machines | 0 | No always-on cost |
| Health check | `GET /health` every 30s | Detects unhealthy instances |
| Persistent volume | 5 GB | Bounded storage |

### Cloud vs Self-Hosted Docker Images

| Image | Tag | Extras | Includes PyTorch | RAM Footprint |
|-------|-----|--------|-----------------|---------------|
| Cloud (default) | `:latest` | `pgvector,gemini` | No | ~90MB idle, ~190MB peak |
| Full (self-hosted) | `:latest-full` | `local,pgvector,gemini` | Yes | ~3.7GB idle, ~13GB peak |

## Per-User Cost Modeling

### Infrastructure (fixed, Fly.io)

| Component | Spec | Cost/mo |
|-----------|------|--------:|
| API server | shared-cpu-1x, 512MB | $3.20 |
| Persistent volume | 5GB | $0.75 |
| Fly Postgres (pgvector) | shared-cpu-1x, 1GB + 10GB vol | $7.20 |
| Bandwidth | ~50GB/mo egress (EU) | $1.00 |
| SSL | Single hostname | $0.10 |
| **Total fixed** | | **$12.25** |

With auto-stop at zero traffic: ~$2/mo (volumes only).

### Variable costs per tier

Assumes average usage (not max). Cost = embedding + enrichment LLM calls.

| Tier | Avg docs/mo | Avg searches/mo | LLM cost/user/mo | Infra share | Total cost/user | Revenue | Margin |
|------|------------|-----------------|------------------:|------------:|----------------:|--------:|-------:|
| **Free** | 30 | 100 | $1.50 | $0.10 | $1.60 | $0 | -$1.60 |
| **Pay As You Go** | 100 | 500 | $5.00 | $0.30 | $5.30 | ~$5–10 | ~break even |
| **Starter (BYOK)** | 200 | 2,000 | $0 | $0.50 | $0.50 | $9.99 | **+$9.49** |
| **Pro** | 500 | 5,000 | $25.00 | $1.00 | $26.00 | $19.99 | -$6.01 |
| **Business** | 1,000 | 10,000 | $50.00 | $3.00 | $55.00 | $29.99 | -$25.01 |

### Margin concerns

**Pro and Business tiers are negative-margin** at heavy usage because enrichment LLM costs scale linearly with documents. Mitigations:

1. **Switch to cheapest viable enrichment model** — GPT-4o-mini ($0.02/doc) vs Gemini 2.5 Flash ($0.05/doc) vs Haiku 4.5 ($0.13/doc). GPT-4o-mini is 6x cheaper than Gemini Flash for enrichment.
2. **Cap monthly documents** instead of daily — Pro at 200 docs/mo, Business at 500 docs/mo.
3. **Add overage pricing** — $0.10/doc past the base quota.
4. **Raise Pro to $24.99, Business to $49.99** — or both.
5. **Starter (BYOK) is the highest-margin tier** — zero LLM cost to us. Push this in marketing.
6. **Free tier** costs ~$1.60/user/mo — consider capping at 3 docs/day instead of 5.

### Scaling projections

| Active users | Fixed infra | Variable LLM | Total/mo |
|-------------|------------:|-------------:|---------:|
| 10 | $12 | ~$50 | ~$62 |
| 100 | $15 | ~$500 | ~$515 |
| 1,000 | $45 | ~$5,000 | ~$5,045 |
| 10,000 | $200 | ~$50,000 | ~$50,200 |

**~97% of cost is LLM API calls. Infrastructure is negligible.**

At 1,000+ concurrent users, upgrade to performance-1x 2GB (~$32/mo).

## Worst-Case Cost Scenarios

### Scenario 1: Large document ingestion (1000 pages)
- ~5000 L3 chunks
- Enrichment: ~1M tokens → **capped at `max_llm_tokens_per_document` (1M) or `max_llm_cost_per_document` ($5)**
- Embeddings (OpenAI): ~$0.80
- Embeddings (local): $0
- **Total: $0.80–5.80 per document** (hard capped)

### Scenario 2: Search abuse (100 searches/minute)
- Rate limited to 60/min by SlowAPI
- With HyDE: 60 LLM calls/min → cached after first call for identical queries
- Without HyDE: $0 per search (no LLM calls)
- **Total: $0–0.60/min** (rate limited + cached)

### Scenario 3: Free tier user trying to exceed limits
- 5 document cap enforced → 403 on 6th ingestion
- Enrichment disabled → no LLM cost
- 100 requests/day cap → 429 after 100
- 50 MB file size → 413 on larger files
- **Total: $0** (all gated)

### Scenario 4: Pro user at max usage (30 days)
- 500 docs/day × 30 = 15,000 docs
- Enrichment: 15,000 × $0.05 = **$750** (Gemini 2.5 Flash)
- Embeddings: 15,000 × $0.0015 = $22.50
- **Total: ~$772/mo** for a $19.99 subscription → catastrophic loss
- **Mitigation: monthly cap or per-doc overage pricing is critical for Pro/Business**

## Missing Controls (Known Gaps)

These are documented for future implementation:

1. **No per-user storage quota** — users can't exceed document count, but storage per document is unbounded
2. **No request log retention policy** — `api_request_log` table grows unbounded in Supabase
3. **No embedding API rate limiting** — relies on provider-side rate limits
4. **Daily quota reset** — `requests_per_day` check uses today's `api_key_usage` rows, but no explicit reset job (rows accumulate naturally by date)
5. **Job queue depth** — no cap on queued (pending) jobs, only on concurrent workers
6. **Supabase tiers out of sync** — database `tier_limits` table still uses Free/Premium/Admin, needs migration to match new 5-tier pricing structure
7. **No monthly document cap** — current limits are per-day, allowing Pro users to ingest 15K docs/mo. Monthly caps needed for margin protection.
8. **`models/costs.py` rates may be stale** — must be kept in sync with provider pricing. Claude 3 Haiku ($0.25/$1.25) deprecated April 2026, Gemini 2.0 Flash ($0.10/$0.40) deprecated June 2026.
