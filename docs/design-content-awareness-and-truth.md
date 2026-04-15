# Design: Content-Aware Tiers, Surprise Scoring, Version-Aware Search & Entity Resolution

Four proposed capabilities that make Ingestible smarter about *what* it's ingesting, *how novel* it is, *whether it's still current*, and *how entities connect across documents*.

**Guiding principle:** All four features are **opt-in and off by default**. A user ingesting one PDF sees zero difference. These activate when the use case demands it — large corpus, multiple versions, overlapping documents.

---

## 1. VBC — Content-Tier Classification

### Problem

Ingestible treats all content uniformly. A code block, a legal clause, a math formula, and a conversational paragraph all go through the same chunking → enrichment → embedding pipeline. This causes real issues:

- **Code and formulas get summarized.** Stage 4 asks the LLM to produce a 2-3 sentence summary of `SELECT * FROM users WHERE id = $1`. The summary is less useful than the original, and the LLM call is wasted tokens.
- **Verbatim content gets chunked.** A 600-token code block that should stay atomic gets split across two L3 passages because it exceeds `INGEST_MAX_CHUNK_TOKENS`. Now neither chunk is useful without the other.
- **Embedding quality varies by content type.** E5-large-v2 produces meaningful embeddings for natural language prose. For minified JSON, base64 blobs, or regex patterns, the embedding is noise. Querying against these embeddings returns false positives.
- **Token economics are wrong.** The core value proposition is token reduction (88-99%). But you can't reduce a SQL query or a config file — the tokens *are* the content. Claiming 88% reduction when half the corpus is code overstates the actual savings.

### Proposal

Add a lightweight content classifier that runs between Stage 1b (Clean) and Stage 2 (Structure), assigning each content block a **tier** that controls downstream behavior:

| Tier | Content type | Chunking | Enrichment | Embedding |
|------|-------------|----------|------------|-----------|
| **T0 — Verbatim** | Code, formulas, configs, legal citations, regex, API signatures | Atomic (never split) | Skip summarization; extract only `keywords` and `concepts` | Embed with code-specific prefix or skip |
| **T1 — Structural** | JSON payloads, structured data, tables, key-value pairs | Atomic or row-grouped | Minimal: extract schema/structure, skip paraphrase | Embed keys/headers, not values |
| **T2 — Extractive** | Dense factual prose (definitions, specifications, procedures) | Normal chunking | Full enrichment but summaries must preserve all facts | Normal embedding |
| **T3 — Compressible** | Narrative prose, discussion, commentary, examples | Normal chunking | Full enrichment, aggressive summarization OK | Normal embedding |

**Classification approach — heuristic heads, no LLM needed:**

1. **Structural Pattern Detector** — Indentation depth, bracket density, line-length variance. Code and config have high structural regularity; prose doesn't.
2. **Content-Type Detector** — Regex for URLs, emails, file paths, version numbers, API keys, hex strings, regex patterns. High density → T0/T1.
3. **Information Density** — Named entity ratio, numeric precision, unique-token ratio. High density + low paraphrasability → T2. Low density → T3.
4. **Domain Heuristics** — Code fence markers (` ``` `), LaTeX delimiters (`$...$`, `\begin{}`), legal section numbering (§), API doc patterns (`@param`, `Returns:`).

These are fast (sub-millisecond per block), deterministic, and require no external API calls. They run on individual content blocks *before* chunking, so the tier informs how chunking proceeds.

### What changes

- **Stage 3 (Chunking):** T0/T1 blocks become atomic chunks regardless of token count. Exceeding `max_chunk_tokens` for a T0 block is acceptable — better a 900-token code chunk than two broken halves.
- **Stage 4 (Enrichment):** T0 chunks skip `summary` and `hypothetical_questions`. They still get `keywords` and `concepts` for search. This saves ~40-60% of LLM calls for code-heavy documentation.
- **Stage 5 (Embedding):** T0 chunks can optionally use a different embedding prefix (e.g., `"code: "` instead of `"passage: "`) or be excluded from vector search entirely, relying on BM25 keyword matching instead.
- **Token economics:** The `economics` endpoint can report *actual* compressibility per document — "this document is 60% T3 (compressible) and 40% T0 (verbatim), so realistic token savings are 52%, not 88%."
- **L3 model:** Add `content_tier: Literal["T0", "T1", "T2", "T3"]` field.

### Mixed-tier content within a section

A documentation page typically alternates: prose paragraph → code block → prose paragraph. The classifier runs per content block (paragraphs, code fences, tables), not per section. Rule:

- **T0/T1 blocks always break the chunk boundary.** A code fence becomes its own L3 chunk, regardless of surrounding prose. The preceding prose becomes one chunk, the code block another, the following prose a third.
- **Adjacent same-tier blocks merge normally.** Two consecutive T3 paragraphs chunk together as they do today.
- **Each L3 chunk gets a single tier.** No mixed-tier chunks. The chunk's tier is the tier of its content blocks (which are all the same, because tier transitions force chunk boundaries).

This means code-heavy documentation produces more, smaller chunks than today. That's correct behavior — each chunk is self-contained and searchable.

### Where this fits in the pipeline

```
Stage 1 (Parse) → Stage 1b (Clean) → [NEW: Stage 1c — Classify] → Stage 2 (Structure) → ...
```

Classification happens on raw content blocks before structure detection, so structural headings vs. code blocks are already separated.

**Config:** `INGEST_CONTENT_CLASSIFICATION=false` (opt-in). When disabled, all content defaults to T3 (current behavior).

---

## 2. Surprise Scoring — Semantic Novelty Detection

### Problem

When ingesting a corpus, there's massive redundancy. A company's 50 internal docs repeat the same architecture descriptions, the same onboarding steps, the same API patterns. Ingestible currently deduplicates by `content_hash` (exact match only), but semantically near-identical content passes through the full pipeline:

- **Wasted enrichment cost.** If chunk A says "Deploy using `kubectl apply -f deployment.yaml`" and chunk B in another document says "Apply the deployment manifest with `kubectl apply -f deployment.yaml`", both get separate LLM enrichment calls. The second call produces nearly identical output.
- **Redundant search results.** Corpus search returns both chunks ranked similarly. The user sees the same information twice.
- **No signal for what's actually new.** When a user ingests a new document into an existing corpus, there's no way to know which parts contain genuinely new information vs. restating what's already stored. The watcher (`ingest watch`) re-processes everything equally.

### Proposal

After embedding (Stage 5), compute a **surprise score** for each L3 chunk:

```
surprise(chunk) = 1 - avg_cosine_similarity(chunk.embedding, k_nearest_neighbors)
```

Where `k_nearest_neighbors` are the K most similar chunks *already in the corpus* (excluding chunks from the same document, to avoid self-similarity from overlap).

**Score interpretation:**
- `0.0–0.2` — Near-duplicate. This information already exists in the corpus.
- `0.2–0.5` — Familiar territory with some new detail.
- `0.5–0.8` — Substantially new information.
- `0.8–1.0` — Completely novel — nothing like this exists in the corpus.

### What this enables

1. **Skip enrichment for low-surprise chunks.** If `surprise < 0.15`, copy enrichment from the nearest neighbor instead of calling the LLM. For a 50-doc corporate corpus with typical 60-70% redundancy, this cuts enrichment cost by more than half.
2. **Deduplicate search results.** In corpus search, when two results have `surprise < 0.15` relative to each other, collapse them into a single result with source attribution from both documents.
3. **Surface what's new.** `GET /documents/{doc_id}/novel-chunks` returns only chunks with `surprise > 0.5`. When a user ingests a new version of a spec, they can immediately see what changed *semantically*, not just what changed textually.
4. **Prioritize watcher re-processing.** When `ingest watch` detects a changed file, compare new chunks against the existing corpus. Only re-enrich high-surprise chunks.

### Corpus-level concerns

**Cold start.** Surprise scoring is meaningless with fewer than ~5 documents. Scores are unstable — document 1 gets all 1.0s, document 2's scores are relative to only document 1. **Solution:** Surprise scoring auto-disables when corpus has fewer than `INGEST_SURPRISE_MIN_CORPUS` documents (default: 5). Below that threshold, all chunks get `surprise_score = None`.

**Score drift.** When you add document 51, the surprise scores for documents 1-50 are now technically stale relative to the expanded corpus. Full recomputation is O(n·k) across the entire corpus — too expensive to run on every ingestion. **Solution:** Scores are computed at ingestion time and treated as a snapshot, not a live value. A `ingest recompute-surprise` CLI command exists for periodic corpus-wide refresh but is never triggered automatically.

**Cross-collection queries.** Currently each document has its own ChromaDB collection. Surprise scoring needs to search across all collections. **Solution:** Maintain a single corpus-level ChromaDB collection (`_corpus_index`) that mirrors all chunk embeddings with `doc_id` metadata. Updated incrementally during Stage 5. Surprise queries hit this collection with a `where: {doc_id: {$ne: current_doc}}` filter.

### Storage

Add to L3 chunk model:
```python
surprise_score: float | None = None       # 0.0-1.0, computed at corpus level
surprise_nearest: str | None = None       # chunk_id of most similar existing chunk
```

Store in the existing `{chunk_id}.json`. `None` means not computed (corpus too small or feature disabled).

### Where this fits

```
Stage 5 (Embed) → [NEW: Stage 5b — Surprise] → Stage 6 (Store)
```

Requires embeddings to exist, so it runs after Stage 5.

**Config:** `INGEST_SURPRISE_SCORING=false` (opt-in). `INGEST_SURPRISE_MIN_CORPUS=5`. `INGEST_SURPRISE_K=5` (number of neighbors).

---

## 3. Version-Aware Search

### Problem

Documents get updated. A v2 of an API spec deprecates endpoints described in v1. Ingestible stores all versions (via the archive system) but treats them as equally valid in search:

- **Stale results.** Corpus search across 3 versions of an API doc returns chunks from all three, ranked by embedding similarity alone. The user gets deprecated endpoint descriptions alongside current ones with no signal about which to trust.
- **Watcher ingests blindly.** When `ingest watch` picks up a new version of a file, the old version's chunks remain fully active in the search index.

### Proposal: Version-aware search (zero-config)

This is not a state machine. There is no user-facing "truth state" concept. It's a single automatic behavior:

**When a document is re-ingested (`--force`), old version chunks that no longer exist in the new version get a `_version_status = "superseded"` internal flag. Search weights superseded chunks at 0.3x.**

That's it. The user doesn't configure anything, doesn't learn a new API, doesn't manage states. Search results silently prefer the latest version. Superseded chunks still appear when they're the only source on a sub-topic (weighted at 0.3, not excluded), but they rank below current content.

### Implementation

This hooks into two existing systems:

1. **Document versioning** (already done in v0.14). When `--force` re-ingests, old chunks are archived. Currently, archived chunks are simply removed from the search index. Instead: keep them in the index with a `version_status` metadata field in ChromaDB, and apply the 0.3x multiplier in `hybrid.py` RRF scoring.

2. **Content-hash comparison** (already done for selective re-enrichment). Chunks that survive re-ingestion with the same `content_hash` keep `version_status = "current"`. Chunks that exist only in the old version get `version_status = "superseded"`.

### What the user sees

- **Search results:** No change to the response schema. Optionally add `version: "current" | "superseded"` to `SearchResult` for transparency, but it's informational — no action required from the user.
- **CLI:** `ingest list` could show a small indicator next to documents with superseded content, but no new commands.
- **API:** No new endpoints. No `PATCH` for manual state management.

### Storage

Internal field on L3 chunks (in `{chunk_id}.json` and ChromaDB metadata):
```python
_version_status: Literal["current", "superseded"] = "current"
```

Underscore prefix signals this is internal bookkeeping, not a user-facing field.

### What this explicitly does NOT include

These are separate features for separate proposals, if ever needed:

- **Contradiction detection.** Comparing chunks across different documents for semantic conflicts. Requires LLM calls, produces false positives, and introduces complexity (what do you do when a contradiction is detected?). Most Ingestible users ingest their own docs — cross-document contradictions within a single org's corpus are rare.
- **Manual retraction.** A `PATCH` endpoint to mark chunks as wrong. If users want to remove wrong content, they re-ingest the corrected document. Adding a retraction state is a concept users have to learn for marginal benefit.
- **Temporal decay.** Auto-staleness based on document age. A 2019 math textbook isn't stale. A 2024 API doc might be. Getting this right requires domain knowledge Ingestible doesn't have.

**Config:** Always on. No configuration needed. The behavior is invisible and always correct — newer versions of the same document should rank higher. There's no scenario where a user wants the opposite.

---

## 4. Cross-Document Entity Resolution

### Problem

Ingestible's knowledge graph extraction (WP 6.4) produces `(subject, predicate, object)` triples per chunk, deduplicated within a document by exact string match. But across documents, the same entity appears under different surface forms:

- Document A: `("React", "is_a", "JavaScript framework")`
- Document B: `("React.js", "uses", "virtual DOM")`
- Document C: `("the React framework", "authored_by", "Meta")`

These are three separate entities in the current KG. A corpus-level query "what do we know about React?" finds only the chunks where the exact string "React" appears, missing the others.

The concept index has the same problem — `concepts: ["React"]` and `concepts: ["React.js"]` are separate entries.

### Proposal

Add a **canonical entity registry** that resolves surface forms to canonical entities across the corpus:

```
Surface forms              → Canonical entity
─────────────────────────────────────────────
"React"                    → react_framework
"React.js"                 → react_framework
"the React framework"      → react_framework
"ReactJS"                  → react_framework
```

**Resolution strategy (layered, no LLM needed for most cases):**

1. **Normalization.** Lowercase, strip articles ("the", "a"), strip trailing parentheticals ("React (JavaScript library)" → "react"). Handles ~50% of duplicates.
2. **Alias rules.** Common suffixes/prefixes: `.js` → strip for framework names; `lib`/`library`/`framework`/`SDK` → strip. Configurable alias file.
3. **Type-aware embedding similarity.** Embed all entity surface forms. Cluster entities with cosine similarity > 0.92, **but only within the same entity type**. This prevents merging "Java" (Technology) with "Java" (Place). Within each cluster, pick the shortest clean form as canonical.
4. **Corpus-level merge.** When a new document is ingested, its entities are resolved against the existing registry. New surface forms for known entities get added as aliases. Genuinely new entities get new canonical entries.

### False merge mitigation

The 0.92 cosine threshold alone is insufficient. "Java" the language and "Java" the island may have similar embeddings in some contexts. Safeguards:

- **Type constraint.** Only merge entities of the same `type` (Person, Technology, Concept, etc.). Types come from KG extraction. If document A says `type: Technology` and document B says `type: Place`, they stay separate regardless of surface-form similarity.
- **Context window.** When similarity is borderline (0.88–0.95), compare the predicates/objects associated with each entity. If "Java" is associated with `(compiles_to, bytecode)` and "Java" is associated with `(located_in, Indonesia)`, they clearly don't merge.
- **Conservative default.** Better to leave two entities separate than to wrongly merge them. Users can manually merge via an alias file. Wrong merges are harder to undo than missed merges.

### What this enables

- **Unified knowledge graph.** Corpus-level KG queries traverse across documents through canonical entities. "What do we know about React?" returns triples from all three documents.
- **Better concept index.** Concept search resolves aliases: searching "React.js" also finds chunks tagged with "React" or "the React framework."
- **Entity-centric retrieval.** New search mode: "find all chunks that mention entity X" across the corpus, regardless of surface form.
- **Entity cards.** `GET /entities/{entity_id}` returns all known triples, source documents, and surface forms for a canonical entity.

### Storage

New file in corpus root:
```
data/
  entity_registry.json     # canonical entities with aliases and embeddings
  documents/
    {doc_id}/
      entity_map.json      # local surface form → canonical entity_id mapping
```

Entity registry structure:
```json
{
  "react_framework": {
    "canonical_name": "React",
    "aliases": ["React.js", "ReactJS", "the React framework"],
    "type": "Technology",
    "first_seen_in": "doc_abc",
    "document_count": 3,
    "triple_count": 12
  }
}
```

### Where this fits

```
Stage 4 (Enrich + KG extract) → [NEW: Stage 4b — Entity Resolution] → Stage 5 (Embed)
```

Runs after KG extraction because it needs the raw triples. Runs before embedding so that canonical entity names can be used in the concept index and optionally in embedding text.

**Config:** `INGEST_ENTITY_RESOLUTION=false` (opt-in). Requires `INGEST_EXTRACT_KNOWLEDGE_GRAPH=true`.

---

## Implementation Priority

| Feature | Effort | Payoff | Opt-in | Dependencies |
|---------|--------|--------|--------|-------------|
| **VBC Classification** | Medium | High — fixes chunking, saves enrichment cost, corrects token economics | Yes (`INGEST_CONTENT_CLASSIFICATION`) | None |
| **Version-Aware Search** | Low | High — silently fixes the stale-results problem | No (always on) | Document versioning (done) |
| **Surprise Scoring** | Medium | High — cuts redundant enrichment, better corpus search | Yes (`INGEST_SURPRISE_SCORING`) | Needs corpus-level ChromaDB collection |
| **Entity Resolution** | Medium | Medium — biggest impact for multi-doc corpora with overlapping domains | Yes (`INGEST_ENTITY_RESOLUTION`) | KG extraction (done) |

Suggested order: **VBC → Version-Aware Search → Surprise → Entity Resolution.**

- VBC is standalone and immediately useful for any document type.
- Version-aware search is low-effort (hooks into existing versioning + content-hash) and always-on — no adoption friction.
- Surprise scoring builds the corpus-level index that entity resolution also benefits from.
- Entity resolution is the most corpus-dependent — only valuable with 5+ documents with overlapping domains.
