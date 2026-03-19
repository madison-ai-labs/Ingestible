# Architecture Overview

## Pipeline Stages

```
Document → Stage 1 (Parse) → Stage 1b (Clean) → Stage 2 (Structure) → Stage 3 (Chunk)
         → Stage 3b (Validate) → Stage 3c (Contextual) → Stage 4 (Enrich)
         → Stage 5 (Embed & Index) → Stage 6 (Store)
```

### Stage 1 — Document Parsing

**File:** `pipeline/stage1_parsing.py`

Converts a document into structured markdown text. Supports multiple formats:

| Format | Parser | Notes |
|--------|--------|-------|
| PDF | Docling (primary), PyMuPDF4LLM (fallback) | OCR retry when chars/page < 100 |
| DOCX | python-docx + markdownify | |
| HTML | markdownify | |
| EPUB | ebooklib | Chapter-based page splitting |
| PowerPoint | python-pptx | Slide-per-page |
| Excel/CSV | openpyxl / native | Row-based content |
| RST | docutils | |
| AsciiDoc | Native regex parser | |
| Plain text | Native | |

For PDFs, Docling provides deep layout analysis, table detection via TableFormer, heading recognition, and figure extraction. PyMuPDF4LLM is the fallback — faster, simpler markdown extraction with per-page output. If average chars/page < 100 after first pass, parsing retries with OCR enabled.

**Figure extraction:** Docling's `pictures` are extracted as `FigureRef` objects with caption, label, page number, and classification, then attached to their respective pages.

**Output:** `ParsedDocument` with title, page count, TOC entries, per-page markdown content (including tables and figures), and source format.

### Stage 1b — Cleaning

**File:** `pipeline/stage1b_clean.py`

Normalizes whitespace, strips artifacts, and cleans up parser output. Enabled by `INGEST_CLEANING_ENABLED`.

### Stage 2 — Structure Detection

**File:** `pipeline/stage2_structure.py`

Builds a hierarchy tree from the flat document. This is what gives the AI a "map" of the document.

**Strategy (in order of preference):**

1. **Parse embedded TOC tables** — Many documents contain a Table of Contents rendered as markdown tables with page numbers (`| Section Title | 42 |`). These are extracted with page number associations.

2. **Detect headings from markdown** — Falls back to `#`/`##`/`###` heading syntax, numbered section patterns ("1.1 Title", "Chapter 3:"), etc.

3. **Infer hierarchy from page ranges** — When all headings are the same level (common in PDFs where visual hierarchy is lost in conversion), uses page span heuristics:
   - Sections spanning 5+ pages → level 1 (chapter)
   - Sections spanning 2-4 pages → level 2 (section)
   - Sections spanning 1 page → level 3 (subsection)
   - Known patterns: "Risk"/"Mitigations" → always subsections; "Introduction"/"Conclusion" → always top-level

**Output:** `DocumentStructure` — a tree of `StructureNode` objects with titles, levels, page ranges, and content.

### Extraction Profile Resolution

**File:** `profiles.py`

Before chunking, the pipeline auto-detects the document type and selects an extraction profile:

| Profile | Detection | Effect |
|---------|----------|--------|
| `paper` | 3+ academic headings (Abstract, Methodology, etc.) | Citation extraction, methodology, key findings |
| `documentation` | Code blocks + API/install headings, or `.rst`/`.adoc` format | Code-aware enrichment |
| `article` | HTML/Markdown without academic or doc signals | Standard enrichment |
| `general` | Fallback (low-confidence detection) | Standard enrichment |

Heuristic detection is zero-cost. For ambiguous documents (low confidence), an optional LLM fallback classifies the document type (`INGEST_PROFILE_LLM_FALLBACK=true`).

### Stage 3 — Smart Chunking

**File:** `pipeline/stage3_chunking.py`

Produces a 4-level chunk hierarchy from the structure tree:

| Level | What | Size | Purpose |
|-------|------|------|---------|
| L0 | Document | ~500-800 tokens | Title, TOC, executive summary, metadata. Always returned as context. |
| L1 | Chapter | ~300-500 tokens | Chapter title + content preview. For browsing. |
| L2 | Section | ~200-400 tokens | Section title + content preview. Primary browse unit. |
| L3 | Passage | ~250-500 tokens | Actual content chunks. Primary search unit. |

**Chunking strategies** (configurable via `INGEST_CHUNKING_STRATEGY`):
- `paragraph` (default) — split on paragraph boundaries
- `semantic` — split on semantic similarity drops between sentences
- `recursive` — recursive character splitting with overlap

**Chunking rules:**
- Never split mid-paragraph or mid-sentence
- Tables and code blocks are atomic (never split)
- Configurable overlap between adjacent passages (`INGEST_CHUNK_OVERLAP_FRACTION`)
- Small trailing chunks get merged into the previous passage

**Output:** `ChunkSet` with `l0`, `l1_chunks`, `l2_chunks`, `l3_chunks`, and `citations`.

### Stage 3b — Validation

**File:** `pipeline/stage3b_validation.py`

Validates chunk sizes, hierarchy integrity, and content coverage. Catches issues before the expensive enrichment stage.

### Stage 3c — Contextual Chunking

**File:** `pipeline/stage3c_contextual.py`

Adds document-level context to each chunk (parent section title, position in document). Enabled by `INGEST_CONTEXTUAL_CHUNKING`.

### Stage 4 — LLM Enrichment (Optional)

**File:** `pipeline/stage4_enrichment.py`

One-time LLM pass at ingestion that generates metadata for dramatically better retrieval. Runs bottom-up: L3 → L2 → L1 → L0. Enrichment prompts are tailored to the detected extraction profile.

**Per L3 passage, the LLM generates:**
- `summary` — 2-3 sentence summary
- `concepts` — key concepts discussed (extractive)
- `hypothetical_questions` — 3-5 questions this passage answers
- `keywords` — specific terms for BM25 search
- `difficulty_level` — beginner/intermediate/advanced
- `depends_on` — prerequisite concepts
- `cross_references` — related topics

**Per L2 section:** `section_summary`, `key_points`, `concepts_introduced`

**Per L1 chapter:** `chapter_summary`, `main_topics`, `learning_objectives`, `key_takeaways`

**Per L0 document:** `domain`, `document_type`, `target_audience`, `key_concepts`, `executive_summary`, `key_findings`, `methodology`, `limitations`

**For papers:** structured citation extraction with authors, year, title, venue, DOI, and inline reference locations.

**LLM Client abstraction:**
- `OpenAIClient` (default) — uses `gpt-4o-mini` with structured JSON output
- `AnthropicClient` (alternative) — uses Claude Haiku
- Async with `Semaphore(N)` for concurrency control (`INGEST_LLM_CONCURRENCY`)
- Swappable via `INGEST_LLM_PROVIDER` env var

The pipeline works without enrichment (`--skip-enrichment`). Validate the full loop before spending API credits.

### Stage 5 — Embedding & Indexing

**File:** `pipeline/stage5_embedding.py`

Builds three search indexes:

**Vector index (ChromaDB):**
- Model: E5-large-v2 via sentence-transformers, running on MPS (Apple Silicon) or CPU
- Requires `"passage: "` prefix for documents, `"query: "` prefix for queries
- `normalize_embeddings=True` for cosine similarity
- Multiple embeddings per chunk (content, summary, hypothetical questions)
- L0 digest embeddings (executive summary, key findings)
- All point back to the same `chunk_id` — deduplicated at query time
- Configurable dimensions (Matryoshka truncation) and quantization
- Chunk-level cache: unchanged chunks skip re-embedding

**BM25 index (rank-bm25):**
- Classic term-frequency search over `content + keywords`
- Language-aware tokenization (detected via `utils/language.py`)
- Persisted as pickle file

**Concept index:**
- Simple `concept → [chunk_ids]` JSON mapping
- For "tell me everything about X" queries
- Populated from enrichment concepts + keywords

### Stage 6 — Storage

**File:** `pipeline/stage6_storage.py`

Persists everything as a JSON file hierarchy:

```
data/documents/{doc_id}/
  meta.json              # title, pages, ingestion date, L0 chunk, metadata
  structure.json         # full hierarchy tree
  chapters/
    {chapter_id}/
      meta.json          # L1 chunk data
      sections/
        {section_id}/
          meta.json      # L2 chunk data
          chunks/
            {chunk_id}.json  # L3 passage data
  chroma/                # ChromaDB vector index
  bm25_index.pkl         # BM25 sparse index
  concept_index.json     # concept → chunk_ids mapping
  .checkpoint/           # pipeline stage checkpoints (cleared on success)
  archive/               # previous versions (document versioning)
```

## Project Structure

```
src/ingestible/
  cli.py                 # CLI: ingest, list, search, corpus-search, enrich, export, versions, config, serve
  config.py              # pydantic-settings, INGEST_ env prefix
  profiles.py            # Extraction profiles (paper, article, documentation, general)
  web.py                 # Web UI (FastAPI + Jinja2 + htmx)
  api.py                 # REST API (FastAPI)
  models/
    document.py          # ParsedDocument, FigureRef, StructureNode, DocumentStructure
    chunks.py            # L0/L1/L2/L3 chunk models, ChunkSet
    enrichment.py        # LLM output schemas
    metadata.py          # DocumentMetadata
    search.py            # SearchResult, SearchResponse
  pipeline/
    orchestrator.py      # Runs stages 1→6 in sequence, profile resolution
    stage1_parsing.py    # Multi-format document parsing
    stage1b_clean.py     # Content cleaning/normalization
    stage2_structure.py  # Heading detection, TOC extraction, hierarchy building
    stage3_chunking.py   # L0-L3 hierarchy chunking
    stage3b_validation.py # Chunk validation
    stage3c_contextual.py # Contextual chunk augmentation
    stage4_enrichment.py # LLM enrichment (OpenAI / Anthropic)
    stage5_embedding.py  # Embedding generation, ChromaDB + BM25 + concept indexing
    stage6_storage.py    # JSON file hierarchy persistence
    batch.py             # Batch/directory ingestion
    checkpoint.py        # Pipeline checkpoint/resume
    fetch.py             # URL download
    metadata.py          # Document metadata extraction
    progress.py          # Progress callbacks
    re_enrich.py         # Re-enrichment without re-parsing
  search/
    hybrid.py            # RRF-based merge, optional cross-encoder reranking
    vector_store.py      # ChromaDB wrapper
    bm25_store.py        # rank-bm25 wrapper (with language-aware tokenization)
    concept_index.py     # concept → chunk_ids index
    corpus.py            # Cross-document corpus search
  export/
    jsonl.py             # JSONL export
    parquet.py           # Parquet export
    llamaindex.py        # LlamaIndex node export
    langchain.py         # LangChain document export
  adapters/
    cv_export.py         # CognitiveVault export adapter
  utils/
    tokens.py            # tiktoken token counting
    text.py              # paragraph/sentence splitting
    language.py          # Language detection
  templates/             # Jinja2 templates for web UI
```
