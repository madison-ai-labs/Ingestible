# How Search Works

## The Three Search Systems

Every query runs three search systems in parallel, then merges results into one ranked list.

### 1. Vector Search (weight: 0.7)

**What it does:** Finds passages that are _semantically similar_ to the query, even if they share no keywords.

**How:**
- At ingestion, every L3 passage is converted to a 1024-dimensional vector by E5-large-v2
- The model understands meaning — "Reizüberflutung" and "Nervensystem überläuft" end up near each other in vector space
- At query time, the question is converted to the same kind of vector
- ChromaDB finds the closest passage vectors by cosine distance

**With enrichment, each passage produces multiple embeddings:**
- Content embedding (the raw text)
- Summary embedding ("Explains meltdowns as nervous system overload...")
- 3-5 hypothetical question embeddings ("What happens during a meltdown?")

**L0 digest embeddings** are also indexed:
- Executive summary embedding — matches high-level queries about the document
- Key findings embeddings — one per finding, matches specific result queries

All embeddings point back to the same `chunk_id`. At query time, the search runs against all embeddings and deduplicates by chunk — keeping the best match. This means a query like "Was tun bei sensorischer Überlastung?" might match a hypothetical question embedding almost exactly, even if the raw content uses different wording.

**Embedding configuration:**
- Model: configurable via `INGEST_EMBEDDING_MODEL` (default: `intfloat/e5-large-v2`)
- Matryoshka truncation: `INGEST_EMBEDDING_DIMENSIONS` (empty = full dimensions)
- Binary quantization: `INGEST_EMBEDDING_QUANTIZATION` (`none` or `binary`)

**E5-large-v2 specifics:**
- Requires prefix `"passage: "` for indexed documents
- Requires prefix `"query: "` for search queries
- `normalize_embeddings=True` for unit-length vectors (cosine similarity)
- Runs on MPS (Apple Silicon GPU) via sentence-transformers

### 2. BM25 Search (weight: 0.3)

**What it does:** Classic keyword/term-frequency matching. Catches exact term matches that vector search might rank lower.

**How:**
- BM25 (Best Match 25) scores each passage by:
  - How often query terms appear in the passage (term frequency)
  - How rare those terms are across the whole document (inverse document frequency)
  - Passage length normalization
- "Reizüberflutung" appearing in only 3 of 656 passages → very high signal when it does appear
- Indexed over `content + keywords` (keywords populated by enrichment)
- Language-aware tokenization — detected automatically per document

**When BM25 beats vector search:**
- Exact technical terms, names, acronyms
- Rare domain-specific vocabulary
- When the query uses the exact same phrasing as the source

### 3. Concept Index (small boost)

**What it does:** Direct `concept → chunk_ids` lookup for "tell me everything about X" queries.

**How:**
- At ingestion (with enrichment), the LLM extracts concepts from each passage: `["Meltdown", "sensorische Überlastung", "Reizreduktion"]`
- Stored as a JSON mapping: `{"meltdown": ["chunk-1", "chunk-7"], "reizreduktion": ["chunk-1", "chunk-12"]}`
- At query time, a substring match finds all chunks tagged with matching concepts
- Adds a small fixed score boost (0.005) to matched chunks

**Without enrichment:** The concept index is empty. Concepts come from Stage 4 LLM analysis.

## Optional: Cross-Encoder Reranking

When configured (`INGEST_RERANKER_MODEL`), a cross-encoder reranker rescores the top candidates from the initial retrieval:

1. RRF fusion produces a candidate list (top `INGEST_RERANKER_TOP_K`, default 50)
2. Cross-encoder scores each (query, passage) pair
3. Final ranking blends the RRF score with the reranker score (`INGEST_RERANKER_WEIGHT`)

Cross-encoder models are more accurate than bi-encoders but slower — they process query and document together. This is why they're used as a second-pass reranker, not the primary retrieval.

## The Merge: Reciprocal Rank Fusion (RRF)

Each system returns its own ranked list. RRF combines them without needing to normalize scores across systems (which would be comparing apples to oranges):

```
score(chunk) = vector_weight / (K + vector_rank)
             + bm25_weight / (K + bm25_rank)
             + concept_boost
```

Where `K = 60` (standard RRF constant), `vector_weight = 0.7`, `bm25_weight = 0.3`.

### Example

A chunk ranked #1 in vector search and #3 in BM25:
```
0.7 / (60 + 1) + 0.3 / (60 + 3) = 0.01148 + 0.00476 = 0.01624
```

A chunk ranked #10 in vector search only (not in BM25 top results):
```
0.7 / (60 + 10) + 0 = 0.01000
```

The first chunk wins — it appeared in both systems. This is the key property of RRF: **chunks that multiple systems agree on get naturally boosted**.

The `match_sources` field on each result tells you which systems contributed: `["vector", "bm25"]` means both agreed, `["vector"]` means only semantic similarity matched.

### Version-Aware Weighting

When document versioning is active, superseded chunks (from older versions) receive a 0.3x multiplier on their final RRF score. This means current-version results naturally rank higher while older versions remain discoverable if the query specifically matches them.

## Corpus Search (Cross-Document)

**File:** `search/corpus.py`

Corpus search queries all ingested documents simultaneously:

1. Discovers all document directories under `data/documents/`
2. Loads a `HybridSearcher` for each document (LRU-cached)
3. Runs hybrid search against each document in parallel
4. Merges results across documents via cross-document RRF
5. Results include the source document title for attribution

Use via CLI (`ingest corpus-search "query"`) or the web UI search page.

## The Full Retrieval Flow

When an AI queries a document, the interaction follows three steps:

### Step 1: Get the Map (L0)

The AI receives the document overview: title, total pages, executive summary, and the full table of contents with chapter/section titles. This is ~500-800 tokens and gives the AI a structural understanding of where topics live.

### Step 2: Search

The AI sends a natural language query. The hybrid search (vector + BM25 + concept) returns the top N passages ranked by relevance. Each result includes:
- The passage content (or summary if enriched)
- Score and which search systems matched
- Chapter/section location
- Page numbers

### Step 3: Drill Down

The AI can request full content of specific passages or sections based on what looked promising in Step 2.

**Total context per query: ~1,000-2,000 tokens** instead of the full document (which could be 90,000+ tokens for a 500-page book).

## Impact of Enrichment on Search Quality

| Aspect | Without Enrichment | With Enrichment |
|--------|-------------------|-----------------|
| Embeddings per passage | 1 (content only) | 5-6 (content + summary + questions) |
| L0 digest embeddings | None | Executive summary + key findings |
| BM25 index | Content only | Content + extracted keywords |
| Concept index | Empty | Populated with LLM-extracted concepts |
| Query matching | Must match content wording | Can match questions, summaries, concepts |
| Result display | Raw content snippet | Summary + content |

Enrichment is a one-time cost at ingestion. Query time is always cheap (embedding lookup + BM25 score + concept lookup, no LLM in the loop).
