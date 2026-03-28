# How It Works

## The Big Picture

A document goes in. A queryable knowledge store comes out.

Ingestible takes any document — PDF, DOCX, EPUB, HTML, audio, video, even a ZIP archive — and transforms it into a structured, searchable knowledge store that an AI can query efficiently. Instead of dumping an entire 500-page book (92,598 tokens) into a context window, your AI sends a search query and gets back exactly the passages it needs: ~1,317 tokens. That is a 99% reduction.

```
Document (any format)
    ↓
Parse → Clean → Structure → Chunk → Validate → Enrich → Embed & Index → Store
    ↓
Queryable knowledge store (three search indexes, hierarchical chunks, structured metadata)
```

The pipeline runs once per document. Every query after that is cheap — no LLM calls, just index lookups.

## The Pipeline

### Stage 1: Parse

**What it does:** Converts your document into clean, structured markdown — regardless of what format it started as.

Ingestible handles 25+ formats through format-specific parsers:

| Format | How it's parsed |
|--------|----------------|
| PDF | IBM Docling for deep layout analysis (tables, headings, figures). Falls back to PyMuPDF if needed. Retries with OCR if text is sparse. |
| DOCX, PPTX, XLSX | Native Python parsers, converted to markdown |
| EPUB | Chapter-based splitting, each chapter becomes a page |
| HTML / Markdown / RST | Direct conversion to normalized markdown |
| Audio (MP3, WAV, FLAC, ...) | Local Whisper transcription with timestamps |
| Video (MP4, MKV, AVI, ...) | Audio extraction + transcription + keyframe capture |
| Images (PNG, JPG, TIFF, ...) | OCR + layout analysis via Docling |
| Email (EML, MSG) | Headers, body, and inline attachments |
| ZIP archives | Auto-detects Notion exports, Confluence exports, or generic file archives |

**What it produces:** A `ParsedDocument` — title, page count, table of contents, and per-page markdown content with tables and figures preserved.

### Stage 2: Clean

**What it does:** Normalizes the parser output. Strips artifacts, fixes whitespace, removes conversion noise.

This is a small but important step. Parsers, especially PDF parsers, produce inconsistent output: stray line breaks inside paragraphs, duplicated headers, encoding artifacts. The cleaning stage irons these out so downstream stages work with consistent, high-quality text.

### Stage 3: Structure

**What it does:** Builds a hierarchy tree — giving the AI a map of the document.

The structuring engine looks for hierarchy signals in this order:

1. **Embedded TOC tables** — Many PDFs contain a table of contents rendered as a markdown table. These are parsed with page number associations.
2. **Heading patterns** — `#`/`##`/`###` markdown headings, numbered sections ("1.1 Title"), chapter patterns ("Chapter 3:").
3. **Page range heuristics** — When heading levels are ambiguous (common in PDFs where visual hierarchy is lost), the engine infers structure from section length: 5+ pages is a chapter, 2-4 pages is a section, 1 page is a subsection.

**What it produces:** A `DocumentStructure` — a tree of nodes with titles, levels, page ranges, and content. This tree drives how the document gets chunked.

### Stage 4: Chunk

**What it does:** Splits the document into a 4-level hierarchy of chunks, from broad overview down to individual passages.

This is where the token savings come from. Instead of one giant blob of text, the document becomes a navigable tree:

| Level | What it represents | Typical size |
|-------|-------------------|-------------|
| L0 | The whole document | ~500-800 tokens |
| L1 | A chapter | ~300-500 tokens |
| L2 | A section within a chapter | ~200-400 tokens |
| L3 | A single passage | ~250-500 tokens |

Three chunking strategies are available:
- **Paragraph** (default) — splits on natural paragraph boundaries
- **Semantic** — splits where the meaning shifts between sentences
- **Recursive** — recursive splitting with configurable overlap

Key rules the chunker follows:
- Never splits mid-sentence or mid-paragraph
- Tables and code blocks are kept atomic (never split across chunks)
- Small trailing chunks get merged into the previous passage
- Configurable overlap between adjacent passages for continuity

**What it produces:** A `ChunkSet` — the L0 overview, plus lists of L1, L2, and L3 chunks with parent-child relationships.

### Stage 5: Validate

**What it does:** Catches problems before the expensive enrichment stage.

Validation checks chunk sizes, hierarchy integrity, and content coverage. If a chunk is too large, too small, or orphaned from the hierarchy, this stage flags it. Better to catch a structuring issue here than waste LLM credits enriching broken chunks.

### Stage 6: Enrich (optional)

**What it does:** A one-time LLM pass that generates metadata for dramatically better search. This is where retrieval quality jumps from good to excellent.

Enrichment runs bottom-up — L3 passages first, then L2 sections, then L1 chapters, then the L0 document overview. For each level, the LLM generates different metadata:

**Per L3 passage:**
- A 2-3 sentence summary
- Key concepts discussed
- 3-5 hypothetical questions this passage answers
- Keywords for keyword search
- Difficulty level and cross-references

**Per L2 section:** Section summary, key points, concepts introduced

**Per L1 chapter:** Chapter summary, main topics, learning objectives

**Per L0 document:** Domain, document type, target audience, executive summary, key findings

The hypothetical questions are particularly powerful. A passage about "nervous system overflow reactions" gets tagged with questions like "What happens during a meltdown?" — so when a user asks that exact question, vector search finds the passage even though the wording is completely different.

Enrichment is skippable (`--skip-enrichment`). The pipeline works without it — you just get fewer embeddings per passage and no concept index.

**Enrichment cost (using gpt-4o-mini):**

| Document size | Estimated cost | Time |
|---------------|---------------|------|
| 55 pages | ~$0.01 | ~1 min |
| 500 pages | ~$0.20 | ~5 min |
| 1,000 pages | ~$0.50 | ~10 min |

### Stage 7: Embed & Index

**What it does:** Converts chunks into searchable indexes — three of them.

**Vector index (ChromaDB):**
Each chunk is converted into a 1024-dimensional vector using E5-large-v2. With enrichment, each passage produces multiple embeddings: one for the raw content, one for the summary, and one for each hypothetical question. All point back to the same chunk. At query time, the best-matching embedding wins.

L0 digest embeddings (executive summary, key findings) are also indexed, so high-level questions about the document match directly.

**BM25 index:**
Classic keyword search. Scores passages by how often query terms appear, weighted by how rare those terms are across the whole document. Indexed over content plus any keywords extracted during enrichment.

**Concept index:**
A simple mapping from concept names to chunk IDs. When a query mentions "meltdowns," the concept index immediately returns every chunk tagged with that concept.

**What it produces:** Three complementary search indexes, each with different strengths. They get fused at query time.

### Stage 8: Store

**What it does:** Persists everything as a JSON file hierarchy.

```
data/documents/{doc_id}/
  meta.json                  # document metadata + L0 chunk
  structure.json             # full hierarchy tree
  chapters/
    {chapter_id}/
      meta.json              # L1 chapter data
      sections/
        {section_id}/
          meta.json          # L2 section data
          chunks/
            {chunk_id}.json  # L3 passage data
  chroma/                    # vector index
  bm25_index.pkl             # keyword index
  concept_index.json         # concept-to-chunk mapping
  knowledge_graph.json       # entity relationships (when enabled)
```

No database server required. Each document is self-contained in its own directory. Back it up, move it, delete it — it is just files.

## The Chunk Hierarchy

Here is what the four levels look like for a concrete example: a 500-page book about cooking.

**L0 — Document overview (~600 tokens)**
Title, author, executive summary ("A comprehensive guide to French cooking techniques covering knife skills, sauces, pastry, and plating"), and the full table of contents. This is the map. The AI reads this first and knows the entire structure of the book.

**L1 — Chapter summaries (~400 tokens each)**
"Part II: The Five Mother Sauces" — a summary of the chapter covering bechamel, veloute, espagnole, hollandaise, and tomato sauce. Main topics, learning objectives, key takeaways. There might be 15-20 L1 chunks for a 500-page book.

**L2 — Section summaries (~300 tokens each)**
"Chapter 7, Section 3: Hollandaise and Its Derivatives" — summary, key points (temperature control, emulsion science, fixing a broken sauce), concepts introduced. There might be 80-120 L2 chunks.

**L3 — Passages (~350 tokens each)**
The actual text: "To rescue a broken hollandaise, remove the bowl from heat immediately. Add one tablespoon of cold water and whisk vigorously. The temperature shock helps the emulsion re-form..." There might be 600-800 L3 chunks.

When an AI asks "How do I fix a broken hollandaise?", it does not need to read all 500 pages. It gets:
1. The L0 overview (sees that Chapter 7 covers sauces)
2. Search results pointing to the specific L3 passage about rescuing broken hollandaise
3. The full passage content

Total: ~1,500 tokens instead of ~90,000.

## How Search Works

Every query runs three search systems in parallel, then merges results into one ranked list.

### The Three Indexes

**Vector search (weight: 0.7)** finds passages by meaning. "How do I handle sensory overload?" matches a passage about "nervous system overflow reactions" because the embedding model understands they mean the same thing. With enrichment, each passage has 5-6 embeddings (content, summary, hypothetical questions), so there are more chances to match.

**BM25 keyword search (weight: 0.3)** finds passages by exact terms. If you search for "hollandaise" and only 3 passages out of 700 mention that word, those 3 passages get a very strong signal. BM25 catches exact matches that vector search might rank lower.

**Concept index (small boost)** does a direct lookup. If the query mentions a known concept, every chunk tagged with that concept gets a small score bump.

### Reciprocal Rank Fusion (RRF)

The three indexes return separate ranked lists. RRF merges them without needing to normalize scores across systems:

```
score(chunk) = 0.7 / (60 + vector_rank) + 0.3 / (60 + bm25_rank) + concept_boost
```

The key property: **chunks that multiple systems agree on get naturally boosted**. A passage ranked #1 in vector search and #3 in BM25 scores higher than a passage ranked #1 in vector search alone. Cross-validation between systems is a strong relevance signal.

### The Full Retrieval Flow

1. **Get the map** — The AI reads the L0 overview (~500-800 tokens): title, executive summary, table of contents.
2. **Search** — The AI sends a query. Hybrid search returns the top passages with scores, locations, and which search systems matched.
3. **Drill down** — The AI requests the full content of the most promising passages.

Total context per query: ~1,000-2,000 tokens.

## Search Enhancements

Four optional features push search quality further. All are off by default and can be enabled per-query or globally.

**Auto-merge** — When 3 or more L3 passages from the same L2 section all match a query, that is a signal the whole section is relevant. Auto-merge returns the parent L2 section instead of the individual fragments, giving the AI more coherent context. Enable with `--auto-merge` or `INGEST_AUTO_MERGE_ENABLED=true`.

**HyDE (Hypothetical Document Embeddings)** — Instead of embedding the raw query, Ingestible first asks an LLM to generate a hypothetical answer paragraph, then embeds that. The hypothetical answer is closer in vector space to the actual answer than the question is. Useful for complex or abstract queries. Enable with `--hyde` or `INGEST_HYDE_ENABLED=true`.

**Knowledge graph retrieval** — When knowledge graph extraction is enabled during enrichment, Ingestible builds a graph of entity relationships (e.g., "Hollandaise — is_a — Mother Sauce", "Bechamel — uses — Roux"). At search time, the graph finds related chunks that share entities with the top results but might not match by text. Enable with `--kg` or `INGEST_KG_RETRIEVAL_ENABLED=true`.

**Cross-encoder reranking** — A second-pass reranker that processes each (query, passage) pair together for more accurate scoring. Slower than the initial retrieval but more precise. The top candidates from RRF fusion are rescored and reblended. Configure with `INGEST_RERANKER_MODEL`.

## What Makes It Different

The core insight is token economics.

Most RAG systems retrieve chunks and stuff them into context. Ingestible takes a different approach: it builds a hierarchical knowledge store with three complementary search indexes, so the AI reads only what it needs.

### The Numbers

| Document | Full context | Per query | Savings |
|----------|-------------|-----------|---------|
| 55-page research paper | 4,975 tokens | ~585 tokens | 88% |
| 513-page book | 92,598 tokens | ~1,317 tokens | 99% |
| 1,000-page technical manual | ~180,000 tokens | ~2,000 tokens | 99% |

The 1,000-page manual does not even fit in most context windows. Without hierarchical retrieval, the AI simply cannot use it. With Ingestible, it costs ~2,000 tokens per query — room for dozens of queries in a single conversation.

### Why It Works

**Nothing is lost.** All content is stored and indexed. The savings come from the AI reading only what is relevant per query, not from discarding content.

**The hierarchy is the map.** The L0 overview tells the AI the full structure of the document in ~800 tokens. It knows where topics live before searching.

**Semantic search finds meaning, not keywords.** "How do I handle sensory overload?" matches "nervous system overflow reactions" because vector embeddings capture meaning.

**Multiple systems cross-validate.** A passage found by both vector search and keyword search is more likely relevant than one found by only one system. RRF fusion makes this automatic.

**Enrichment pays for itself.** A one-time LLM pass at ingestion (~$0.20 for a 500-page book) generates summaries, hypothetical questions, and concept tags that improve every subsequent query. No LLM calls at search time.
