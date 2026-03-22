# Compliance & Data Governance

This document describes how Ingestible maps to EU/Austrian regulatory requirements and what deploying organizations need to handle on their side.

**Ingestible is a data processing tool, not a legal product.** This document is informational — consult your legal/DPO team for your specific deployment.

---

## GDPR / Austrian DSG

### What Ingestible provides

| Requirement | Implementation | Status |
|-------------|---------------|--------|
| **Right to erasure (Art. 17)** | `DELETE /documents/{doc_id}` removes all data (chunks, indexes, metadata, checkpoints) | Implemented |
| **Access control (Art. 25)** | Per-document access tags, `X-Access-Tags` header filtering at retrieval time | Implemented |
| **Audit trail (Art. 5(2))** | Search queries logged to `data/audit.jsonl` with user, query, results, timestamps | Implemented |
| **Data minimization (Art. 5(1)(c))** | Content-tier classification skips enrichment on verbatim content; selective re-enrichment only processes changed chunks | Implemented |
| **Local processing** | Embeddings run locally with `[local]` extra. LLM enrichment is skippable (`--skip-enrichment`). Zero data leaves your infrastructure if configured this way. | Implemented |
| **Authentication** | Bearer token auth with constant-time comparison (no timing attacks) | Implemented |
| **Webhook integrity** | HMAC-SHA256 signature verification on incoming webhooks | Implemented |

### What the deploying organization must handle

1. **Legal basis for processing (Art. 6)** — Document why you're processing these documents (legitimate interest, contract performance, etc.) in your Record of Processing Activities (ROPA / Verarbeitungsverzeichnis).

2. **Data Processing Agreements** — If using LLM enrichment with OpenAI or Anthropic, sign their DPA (Auftragsverarbeitungsvertrag). Both providers offer standard DPAs:
   - [OpenAI DPA](https://openai.com/policies/data-processing-addendum)
   - [Anthropic DPA](https://www.anthropic.com/policies/data-processing-addendum)

3. **Transfer Impact Assessment** — LLM API providers are US-based. Under the EU-US Data Privacy Framework (currently valid), both are DPF-certified. If the DPF is invalidated, Standard Contractual Clauses (SCCs) apply. To avoid this entirely, use `--skip-enrichment` and `INGEST_EMBEDDING_PROVIDER=local`.

4. **DPIA (Art. 35)** — If processing personal data at scale (e.g., ingesting thousands of employee documents or customer records), a Data Protection Impact Assessment is likely required. The deploying organization must conduct this.

5. **Data retention** — Implement a retention policy for ingested documents. Ingestible provides deletion but not automatic TTL-based expiry. Use `ingest cleanup` or schedule `DELETE /documents/{doc_id}` calls.

6. **Notification to the Austrian DSB** — Breach notifications go to the Datenschutzbehörde. This is an organizational responsibility, not a tool feature.

### Data flow diagram

```
Document → [Ingestible Pipeline — local processing]
                ├── Parse (local)
                ├── Structure (local)
                ├── Chunk (local)
                ├── Enrich (OPTIONAL — sends chunk text to LLM API)
                │       └── OpenAI / Anthropic API (US-based, DPF-certified)
                ├── Embed (local with [local] extra, OR API-based)
                │       └── OpenAI / Cohere / Voyage API (if configured)
                └── Store (local disk / Docker volume)
```

**To keep all data local:** `pip install ingestible[local]` + `--skip-enrichment` — no data leaves your infrastructure.

---

## EU AI Act

### Classification

Ingestible is a **data processing pipeline**, not an AI system under Art. 3(1). It orchestrates parsing, chunking, and calls to external AI models, but does not itself infer, predict, or make decisions.

The obligations under the EU AI Act apply to:
- **GPAI model providers** (OpenAI, Anthropic) — not to Ingestible
- **Deployers of high-risk AI systems** — if Ingestible is used as a component in a system that makes decisions affecting people (HR screening, legal assessment, credit scoring), the deployer must ensure the full system complies

### Timeline

| Date | What |
|------|------|
| Feb 2025 | Prohibited practices ban (in force) |
| Aug 2025 | GPAI model obligations (in force) |
| **Aug 2026** | High-risk system obligations (upcoming) |
| Aug 2027 | Legacy high-risk systems must comply |

### What Ingestible provides for AI Act compliance

- **Transparency** — AI-generated fields are clearly named (`summary`, `hypothetical_questions`, `kg_triples`). Non-AI fields (`content`, `page_start`, `chunk_id`) are deterministic.
- **Quality monitoring** — `ingest eval` measures retrieval quality (Hit Rate, MRR, Precision@K). API: `POST /documents/{doc_id}/eval`.
- **Human oversight** — Enrichment is optional and inspectable. All AI-generated metadata is stored alongside the source content, never replacing it.
- **Documentation** — This file, plus `docs/architecture.md`, describes the full data flow and AI components.

### AI System Card

For deployers building a regulated system on top of Ingestible:

| Property | Value |
|----------|-------|
| **AI models used** | Configurable: Anthropic Claude Haiku (default), OpenAI GPT-4o-mini, or custom |
| **Purpose of AI** | Generate metadata (summaries, concepts, questions) to improve search precision |
| **AI is optional** | Yes — `--skip-enrichment` runs the full pipeline without any AI model |
| **Data sent to AI** | Text content of individual chunks (~250-500 tokens each) |
| **AI outputs** | summary, concepts, hypothetical_questions, keywords, difficulty_level, knowledge_graph_triples |
| **Known limitations** | Enrichment quality depends on the LLM model; factual errors in summaries are possible; KG triples may miss implicit relationships |
| **Bias considerations** | LLM-generated summaries may reflect biases present in the model's training data |
| **Human review** | All AI outputs are stored as metadata alongside original content and can be inspected via API or Web UI |

---

## ISO 27001

ISO 27001:2022 is not legally required but is the standard enterprises in Austria/DACH expect.

### Controls Ingestible addresses

| Control | Coverage | Notes |
|---------|----------|-------|
| A.8.3 Access control | Yes | Bearer auth, per-document access tags |
| A.8.5 Authentication | Yes | HMAC constant-time comparison |
| A.8.9 Configuration management | Yes | Pydantic settings, env vars, TOML config |
| A.8.10 Data deletion | Yes | Full document removal via API |
| A.8.12 Data leak prevention | Yes | Path traversal protection, upload size limits, rate limiting |
| A.8.15 Logging | Partial | Structured logging, search audit trail |
| A.8.24 Cryptography | Partial | HMAC webhooks; encryption at rest is the deployer's responsibility |

### Deployer responsibilities

- **Encryption at rest** — Ingestible stores data as JSON on disk. Use filesystem-level encryption (LUKS, FileVault, BitLocker) or encrypted Docker volumes.
- **TLS** — Run behind a reverse proxy (nginx, Caddy, Traefik) with TLS termination. Ingestible's API runs HTTP by default.
- **Backup/recovery** — The `data/documents/` directory contains all state. Back it up per your retention policy.
- **Vulnerability management** — Monitor dependencies via `pip audit` or Dependabot. CI runs `bandit` security scanning.

---

## ISO 42001 (AI Management System)

ISO 42001:2023 is organizational-level, not tool-level. Ingestible supports compliance through:

- Documented AI components and data flows (this file + `docs/architecture.md`)
- AI output quality evaluation (`ingest eval`, `POST /documents/{doc_id}/eval`)
- Configurable AI model selection
- Option to disable AI entirely (`--skip-enrichment`)
- Transparent AI-generated vs. deterministic field labeling

---

## Quick reference for Austrian deployments

| Question | Answer |
|----------|--------|
| Does data leave Austria? | Not by default. With `[local]` + `--skip-enrichment`, everything stays local. With LLM enrichment, chunk text goes to US-based APIs (DPF-certified). |
| Do I need a DPIA? | Likely yes if processing personal data at scale with LLM enrichment. |
| Who is the data controller? | The organization deploying Ingestible. |
| Who is the data processor? | OpenAI/Anthropic (for LLM enrichment), Cohere/Voyage (for API embeddings) — only if configured. |
| Which supervisory authority? | Datenschutzbehörde (DSB), Wien. |
| Is Ingestible a high-risk AI system? | No. It's a data processing pipeline. The deployer's overall system may be. |
| Do employees have access rights? | Yes — Art. 15 GDPR. The deployer must handle subject access requests. |
