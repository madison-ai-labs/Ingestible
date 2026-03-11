# Architecture Overview

## Pipeline Stages

```
PDF → Stage 1 (Parse) → Stage 2 (Structure) → Stage 3 (Chunk)
    → Stage 4 (Enrich) → Stage 5 (Embed & Index) → Stage 6 (Store)
```

### Stage 1 — PDF Parsing

**File:** `pipeline/stage1_parsing.py`

Converts a PDF into structured markdown text.

- **Primary parser:** Docling (IBM) — deep layout analysis, table detection via TableFormer, heading recognition
- **Fallback parser:** PyMuPDF4LLM — faster, simpler markdown extraction with per-page output
- **OCR retry:** If average chars/page < 100 after first pass, re-parses with OCR enabled

Docling returns one monolithic markdown string via `export_to_markdown()`. The parser distributes this across the known page count by splitting on heading boundaries.

**Output:** `ParsedDocument` with title, page count, TOC entries, and per-page markdown content.

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

### Stage 3 — Smart Chunking

**File:** `pipeline/stage3_chunking.py`

Produces a 4-level chunk hierarchy from the structure tree:

| Level | What | Size | Purpose |
|-------|------|------|---------|
| L0 | Document | ~500 tokens | Title, TOC, metadata. Always returned as context. |
| L1 | Chapter | ~300-500 tokens | Chapter title + content preview. For browsing. |
| L2 | Section | ~200-400 tokens | Section title + content preview. Primary browse unit. |
| L3 | Passage | ~250-500 tokens | Actual content chunks. Primary search unit. |

**Chunking rules:**
- Never split mid-paragraph or mid-sentence
- Tables and code blocks are atomic (never split)
- ~10% overlap between adjacent passages
- Small trailing chunks get merged into the previous passage

**Output:** `ChunkSet` with `l0`, `l1_chunks`, `l2_chunks`, `l3_chunks`.

### Stage 4 — LLM Enrichment (Optional)

**File:** `pipeline/stage4_enrichment.py`

One-time LLM pass at ingestion that generates metadata for dramatically better retrieval. Runs bottom-up: L3 → L2 → L1 → L0.

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

**Per L0 document:** `domain`, `key_concepts`

**LLM Client abstraction:**
- `OpenAIClient` (default) — uses `gpt-4o-mini` with structured JSON output
- `AnthropicClient` (alternative) — uses Claude Haiku
- Async with `Semaphore(10)` for concurrency control
- Swappable via `INGEST_LLM_PROVIDER` env var

The pipeline works without enrichment (`--skip-enrichment`). Validate the full loop before spending API credits.

### Stage 5 — Embedding & Indexing

**File:** `pipeline/stage5_embedding.py`

Builds three search indexes:

**Vector index (ChromaDB):**
- Model: E5-large-v2 via sentence-transformers, running on MPS (Apple Silicon)
- Requires `"passage: "` prefix for documents, `"query: "` prefix for queries
- `normalize_embeddings=True` for cosine similarity
- Multiple embeddings per chunk (content, summary, hypothetical questions)
- All point back to the same `chunk_id` — deduplicated at query time
- Batch size: 500

**BM25 index (rank-bm25):**
- Classic term-frequency search over `content + keywords`
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
  meta.json              # title, pages, ingestion date, L0 chunk
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
```

## Project Structure

```
src/ingestible/
  cli.py                 # CLI: ingest, list, search
  config.py              # pydantic-settings, INGEST_ env prefix
  models/
    document.py          # ParsedDocument, StructureNode, DocumentStructure
    chunks.py            # L0/L1/L2/L3 chunk models, ChunkSet
    enrichment.py        # LLM output schemas
    search.py            # SearchResult, SearchResponse
  pipeline/
    orchestrator.py      # Runs stages 1→6 in sequence
    stage1_parsing.py
    stage2_structure.py
    stage3_chunking.py
    stage4_enrichment.py
    stage5_embedding.py
    stage6_storage.py
  search/
    hybrid.py            # RRF-based merge
    vector_store.py      # ChromaDB wrapper
    bm25_store.py        # rank-bm25 wrapper
    concept_index.py     # concept→chunk_ids index
  utils/
    tokens.py            # tiktoken token counting
    text.py              # paragraph/sentence splitting
```
