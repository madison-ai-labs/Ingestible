# Privacy & Original-Document Retention

Ingestible is designed to run on infrastructure you control — typically a
single Docker container on a private network. Even so, ingested documents
can contain PII, regulated material (ISO standards, SOPs, medical or
financial records), or commercially sensitive IP. This page describes
what the system stores, when, and the knobs you have to reduce exposure.

## What gets persisted per document

For every ingested document, Ingestible writes a directory under
`data/documents/{doc_id}/`:

| Artifact | Always written? | Purpose |
|---|---|---|
| `meta.json` | yes | Title, page count, tags, content hash, schema version. |
| `structure.json` | yes | Heading hierarchy / TOC. |
| `chapters/**` | yes | L1/L2/L3 chunks — the text used for search. |
| `indices/**` | yes | ChromaDB vector index, BM25, concept index. |
| `citations.json`, `knowledge_graph.json` | if enrichment ran | LLM-derived metadata. |
| `figures/` | if present | Extracted images. |
| `original.{ext}` | **only if `retain_original=true`** | Verbatim copy of the uploaded file. |

The derived artifacts (chunks, indexes, enrichment) always exist — they are
what makes the document searchable. The **original file is opt-in**.

## The `retain_original` flag

`POST /ingest` accepts a `retain_original` form field (default `false`).

- **`retain_original=false` (default)** — the uploaded bytes are written to a
  temporary file, parsed, and deleted. Nothing on disk after ingestion
  can reconstruct the original PDF byte-for-byte. `GET /documents/{id}/pdf`
  returns `404` for these documents. Search, chunks, and enrichment still
  work normally.
- **`retain_original=true`** — the uploaded file is copied to
  `{doc_dir}/original{ext}` so that `GET /documents/{id}/pdf` can serve it
  back for in-browser rendering (e.g. the Onboarding Deep Dive workspace).

### How to choose

| Case | Recommendation |
|---|---|
| Published standards, learning material you want to render in a viewer | `retain_original=true` |
| Internal SOPs shared with a team | `retain_original=true` + `access_tags` to scope visibility |
| Personal notes, customer-confidential PDFs, classified material | `retain_original=false` — accept the chunk-text fallback in the viewer |
| You're not sure | `retain_original=false`. The decision is reversible by re-ingesting. |

### Why the default is `false`

Retention is opt-in because the safest bytes are the ones that aren't on
disk. If the API is ever exposed, the container host is compromised, or a
backup leaks, documents ingested with `retain_original=false` have no
verbatim copy to exfiltrate — only chunked text and embeddings, which are
already a lossy projection of the source.

## Access control for retained originals

`/documents/{id}/pdf` honors the same access-tag model as search. When
`INGEST_ACCESS_CONTROL_ENABLED=true`:

- Documents ingested with `access_tags=["team-alpha"]` require the caller
  to send `X-Access-Tags: team-alpha` (or any other intersecting tag).
- Documents ingested with no `access_tags` are open to any authenticated
  caller — the "shared with the whole workspace" mode.
- Mismatch → `403`. Missing document → `404`. Wrong media type → `415`.

This is attribute-based (tag intersection), not role-based, so one
document can be simultaneously visible to `team-alpha` and `team-beta`
by ingesting it with both tags.

## HTTP caching of PDF responses

`GET /documents/{id}/pdf` sets `Cache-Control: no-store`. This means:

- The browser will not write the PDF bytes to its disk cache.
- Any HTTP proxy in the request path must not store the response.
- Subsequent requests always hit Ingestible (Range support keeps this
  cheap — PDF.js only re-fetches the pages the user scrolls to).

**Do not put a shared cache or CDN in front of `/pdf`** unless you first
add signed URLs (see below). `no-store` is advisory; a misconfigured
cache layer can still persist the bytes.

## Auditing

When `INGEST_AUDIT_ENABLED=true`, every `/pdf` fetch appends a record to
`data/audit.jsonl`:

```json
{"timestamp": 1712345678.9, "event": "access", "user": "key-abc",
 "doc_id": "iso-42001-2023-…", "resource": "pdf",
 "bytes_served": 4110, "range_start": 0, "range_end": 4109}
```

Combined with the existing `ingest`, `search`, and `delete` events, this
gives you a full data-lifecycle trail suitable for GDPR Art. 15 (access)
and Art. 17 (erasure) evidence.

## Deleting an original after the fact

`DELETE /documents/{id}` removes the entire `{doc_dir}`, including any
retained original. There is currently no endpoint to drop *just* the
retained original while keeping the chunks — if you need that, delete
and re-ingest with `retain_original=false`.

## Threat model — what this design protects against, and what it doesn't

**Protects against:**
- API key leak → if `access_control_enabled` is on, the key alone doesn't
  unlock tagged documents.
- Container host compromise after the fact → documents ingested with
  `retain_original=false` have no byte-exact copy to recover.
- Backup / snapshot of the data volume → same as above; backups of
  `retain_original=false` documents contain only chunk text and vectors.
- Misconfigured nginx / browser extension caching PDF bytes → `no-store`
  is the correct explicit signal.

**Does not protect against:**
- Chunk text itself — the searchable text is stored as JSON and is not
  encrypted at rest. If you can read `data/documents/`, you can read the
  body of every chunk. Encrypt the data volume if this matters.
- Embeddings leaking content — modern embedding inversion attacks can
  recover approximate text from vectors. Treat the ChromaDB index with
  the same sensitivity as the chunk files.
- Enrichment side-channels — if you run enrichment against a third-party
  LLM (OpenAI, Anthropic), the chunk text is sent to that provider. Use
  a local LLM for maximum confidentiality.
- Prompt-injection exfiltration at query time — out of scope for this
  document; see the RAG security references below.

## Future work

- **Signed URL endpoint** (`GET /documents/{id}/pdf-url?ttl=300`) — returns
  a short-lived, HMAC-signed URL so a browser viewer can fetch `/pdf`
  without plumbing bearer tokens, and so you can safely offload serving
  to a CDN. Not yet implemented.
- **At-rest encryption hook** — per-document AES with a key per access
  tag. Currently left to the operator (encrypt the volume, or run on a
  FileVault / LUKS host).
- **Retention TTL** — automatic deletion of retained originals after N
  days while keeping chunks. Currently manual.

## References

- Pinecone, *RAG with Access Control* — attribute-based retrieval.
- Zilliz, *Permission-aware RAG deployments* — why RBAC alone is
  insufficient.
- Thales, *RAG Security* — audit / WORM recommendations.
- MDN, *Cache-Control* — `no-store` vs. `no-cache` semantics.
