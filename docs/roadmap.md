# IngestionTool Feature Expansion — Full Roadmap

## Phase 1: Foundation & Batch Operations (v0.10)

| WP | Feature | Status |
|----|---------|--------|
| 1.1 | Pipeline Checkpoint/Resume | **done** (v0.10) |
| 1.2 | Batch/Directory Ingestion | **done** (v0.9) |
| 1.3 | Document Metadata Extraction | **done** (v0.10) |
| 1.4 | URL Ingestion | **done** (v0.10) |

### WP 1.1: Pipeline Checkpoint/Resume

After each pipeline stage, serialize the intermediate Pydantic model to `{doc_dir}/.checkpoint/{stage_name}.json`. On re-entry, detect the latest checkpoint and resume from there. Delete checkpoints on successful completion.

- **Create:** `src/ingestible/pipeline/checkpoint.py` — `save_checkpoint()`, `load_checkpoint()`, `clear_checkpoints()`
- **Modify:** `orchestrator.py` — wrap each stage with checkpoint save/load; add `resume: bool = True` param
- **Modify:** `config.py` — add `checkpoint_enabled: bool = True`
- **Modify:** `cli.py` — add `--no-checkpoint` flag

### WP 1.2: Batch/Directory Ingestion — DONE

Already implemented in `pipeline/batch.py` with `discover_files()`, `ingest_batch()`, `BatchReport`/`FileResult` dataclasses. CLI dispatches via `_is_batch_input()`. API has `POST /ingest/batch`.

### WP 1.3: Document Metadata Extraction

Extract author, creation date, language, subject, keywords from PDF metadata (via pymupdf/Docling) and DOCX core properties (via python-docx). Populate existing empty `L0Chunk.author` and `ParsedDocument.detected_language` fields.

- **Create:** `src/ingestible/pipeline/metadata.py` — `extract_metadata()` with per-format extractors
- **Create:** `src/ingestible/models/metadata.py` — `DocumentMetadata` Pydantic model
- **Modify:** `orchestrator.py` — call `extract_metadata()` between Stage 1 and Stage 1b
- **Modify:** `models/document.py` — add `metadata: DocumentMetadata | None` to `ParsedDocument`
- **Modify:** `models/chunks.py` — add `creation_date`, `source_language` to `L0Chunk`
- **Modify:** `stage6_storage.py` — include metadata in `meta.json`

### WP 1.4: URL Ingestion

Detect URL input (`http://` / `https://`), download to temp file, detect content type, hand off to existing `parse_document()`. For HTML URLs, optionally use `readability-lxml` for article extraction.

- **Create:** `src/ingestible/pipeline/fetch.py` — `fetch_url(url) -> Path` with content-type sniffing
- **Modify:** `orchestrator.py` — URL detection at top of `ingest()`
- **Modify:** `api.py` — add `POST /ingest/url` endpoint
- **Modify:** `pyproject.toml` — add `httpx>=0.27` dependency

---

## Phase 2: Cross-Document Search & Export (v0.11)

| WP | Feature | Status |
|----|---------|--------|
| 2.1 | Cross-Document Search | **done** (v0.11) |
| 2.2 | Re-enrichment Without Re-parsing | **done** (v0.11) |
| 2.3 | Export to Portable Formats | **done** (v0.11) |

### WP 2.1: Cross-Document Search
`CorpusSearcher` discovers all doc dirs, loads per-document `HybridSearcher` instances (with LRU cache), queries each in parallel, merges results via cross-document RRF.

### WP 2.2: Re-enrichment Without Re-parsing
Load existing chunks from disk, re-run Stage 3c + Stage 4 + Stage 5 + Stage 6. Skips parse/structure/chunk.

### WP 2.3: Export to Portable Formats
Export stored documents to JSONL, Parquet, LlamaIndex nodes, LangChain documents.

---

## Phase 3: Format Expansion (v0.12)

| WP | Feature | Status |
|----|---------|--------|
| 3.1 | EPUB | **done** (v0.12) |
| 3.2 | CSV/Excel | **done** (v0.12) |
| 3.3 | PowerPoint | **done** (v0.12) |
| 3.4 | RST & AsciiDoc | **done** (v0.12) |
| 3.5 | Image/Figure Extraction from PDFs | planned |

---

## Phase 4: Embedding & Search Enhancements (v0.13)

| WP | Feature | Status |
|----|---------|--------|
| 4.1 | Configurable Embedding Dimensions / Quantization | **done** (v0.13) |
| 4.2 | Language Detection + Multilingual BM25 | **done** (v0.13) |

---

## Phase 5: Production Hardening (v0.14)

| WP | Feature | Status |
|----|---------|--------|
| 5.1 | Document Versioning | **done** (v0.14) |
| 5.2 | Streaming Progress Callbacks | **done** (v0.14) |
| 5.3 | Chunk-Level Cache Invalidation | **done** (v0.14) |

---

## Dependency Graph

```
Phase 1 (parallel, no deps):
  WP 1.1 Checkpoint ──┐
  WP 1.2 Batch ✓ ─────┤
  WP 1.3 Metadata ────┤
  WP 1.4 URL ─────────┘
           │
Phase 2 (after Phase 1):
  WP 2.1 Cross-doc search ── needs WP 1.2 (multi-doc corpus)
  WP 2.2 Re-enrichment ───── benefits from WP 1.1 (checkpoints)
  WP 2.3 Export ───────────── standalone
           │
Phase 3 (can overlap with Phase 2):
  WP 3.1-3.4 New formats ─── all independent
  WP 3.5 Figure extraction ── standalone
           │
Phase 4 (after Phase 2):
  WP 4.1 Embedding config ── standalone
  WP 4.2 Multilingual BM25 ─ benefits from WP 1.3 (language detection)
           │
Phase 5 (after Phases 1-2):
  WP 5.1 Versioning ────── needs WP 1.1 (checkpoint awareness)
  WP 5.2 Progress ────────── needs WP 1.2 (batch progress)
  WP 5.3 Chunk cache ─────── needs WP 5.1 (old version to diff)
```
