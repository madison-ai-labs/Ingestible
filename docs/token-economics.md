# Token Economics

## The Problem

An AI reading a 500-page book needs ~90,000 tokens of context. Most LLM context windows cap at 128K-200K tokens, and more context = slower responses + higher cost. But for any given question, the AI only needs 1-2 relevant passages — maybe 500 tokens.

The challenge: finding those 500 tokens without reading all 90,000.

## The Solution: Hierarchical Retrieval

Instead of dumping the entire document into context, the pipeline gives the AI three levels of access:

| Step | What the AI gets | Tokens | Purpose |
|------|-----------------|--------|---------|
| 1. Map | L0 overview + table of contents | ~500-800 | Know what's in the book and where |
| 2. Search | Top 5 ranked passage snippets | ~300-500 | Find which passages are relevant |
| 3. Drill | Full content of 1-2 best passages | ~300-600 | Read the actual answer |
| **Total** | | **~1,000-2,000** | |

## Real-World Numbers

### 55-page research paper (MCP Interoperability)

```
Full document:     4,975 tokens
Per query:          ~585 tokens
Savings:              88%
```

### 513-page German book (So ticke ich)

```
Full document:    92,598 tokens
Per query:        ~1,317 tokens
Savings:              99%
```

### Projected: 1,000-page technical book

```
Full document:   ~180,000 tokens (exceeds most context windows)
Per query:         ~2,000 tokens
Savings:              99%
```

The 1,000-page book **doesn't even fit** in a single context window. Without this pipeline, the AI simply can't use it. With the pipeline, it costs ~2,000 tokens per query — room for dozens of queries in one conversation.

## What Makes It Work

### Nothing is lost

All content is stored and indexed. The savings come from the AI reading only what's relevant per query, not from discarding content.

### The hierarchy is the map

The L0 overview (~800 tokens) tells the AI the full structure:

```
Teil I: Mich verstehen
  Kapitel 1: Mein Kopf funktioniert anders
  Kapitel 3: Meine Sinne und ich
Teil II: Schwierige Momente
  Kapitel 9: Wenn alles zu viel wird (Meltdowns)
  ...
```

The AI can see that a question about sensory overload should look in Kapitel 3 and Kapitel 9 — without reading 500 pages to figure that out.

### Semantic search finds meaning, not keywords

"How do I handle sensory overload?" matches a passage about "nervous system overflow reactions" because vector embeddings capture meaning. The AI doesn't need the exact keyword to find the right passage.

### Multiple retrieval systems cross-validate

A passage found by both vector search AND keyword search is more likely relevant than one found by only one system. RRF fusion naturally ranks cross-validated results higher.

## Enrichment ROI

Enrichment is a one-time ingestion cost. The return is better search precision at every query:

| | Without enrichment | With enrichment |
|---|---|---|
| Embeddings per passage | 1 | 5-6 |
| What gets matched | Raw content wording | Content + summaries + hypothetical questions + concepts |
| Concept index | Empty | Populated |
| Typical precision | Good | Significantly better |

**Cost estimate for enrichment (gpt-4o-mini):**

| Document size | Passages | Estimated cost | Time |
|--------------|----------|---------------|------|
| 55 pages | ~30 | ~$0.01 | ~1 min |
| 500 pages | ~650 | ~$0.20 | ~5 min |
| 1,000 pages | ~1,300 | ~$0.50 | ~10 min |

The enrichment runs once. Every subsequent query benefits without any API cost.
