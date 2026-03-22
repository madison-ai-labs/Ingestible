# Retrieval Quality Audit

**Date:** 2026-03-22
**Documents evaluated:** 3 academic papers (RECOMP, Selective Context, LLMLingua-2)
**Queries:** 15 manual Q&A pairs (5 per document)
**Metrics:** Hit Rate@5, MRR, Precision@5, Recall@5, NDCG@5

## Executive Summary

BM25 outperformed hybrid search on 2 of 3 documents under the old default weights (vector 0.7 / BM25 0.3). **All issues identified in this audit have been fixed:**

- Default weights changed to 0.4/0.6 (vector/BM25) — **MRR improved +0.08, NDCG improved +0.12**
- Added exact-match term boost for entity/acronym queries
- Added NDCG@5 metric and quality floor assertions
- Added CI regression test for search quality

No documents have enrichment data, so the enrichment-driven retrieval boost (hypothetical questions, concept index) remains untested on real data.

---

## 1. Strategy Comparison (cross-document averages)

| Strategy | Hit@5 | MRR | NDCG@5 |
|---|---|---|---|
| **bm25_only** | **100.0%** | **0.9000** | **0.7157** |
| **hybrid_30_70** | 93.3% | **0.9000** | **0.7157** |
| hybrid_50_50 | 93.3% | 0.8167 | 0.6484 |
| hybrid_default (70/30) | 93.3% | 0.7856 | 0.6368 |
| hybrid_80_20 | 93.3% | 0.7767 | 0.6198 |
| vector_only | 80.0% | 0.7500 | 0.5301 |

**Key finding:** BM25-only achieves the best scores across all metrics. The default hybrid (70/30 vector/BM25) actually *degrades* MRR by 0.11 and NDCG by 0.08 compared to pure BM25. The 30/70 vector/BM25 split matches BM25 performance exactly — the vector signal doesn't help but also doesn't hurt at that weight.

## 2. Per-Document Breakdown

### RECOMP (69 chunks, prompt compression paper)

| Strategy | Hit@5 | MRR | NDCG@5 |
|---|---|---|---|
| bm25_only | **100%** | **0.90** | **0.68** |
| hybrid_30_70 | 80% | 0.70 | 0.55 |
| hybrid_default | 80% | 0.51 | 0.41 |
| vector_only | 40% | 0.40 | 0.23 |

Worst document for vector search. The query "How does DPR perform on out-of-domain datasets?" missed entirely — vector search returned semantically similar but wrong chunks (general retrieval discussion instead of the specific DPR performance paragraph). BM25's keyword matching found "DPR" and "out-of-domain" immediately.

### Selective Context (46 chunks, self-information filtering paper)

| Strategy | Hit@5 | MRR | NDCG@5 |
|---|---|---|---|
| hybrid_30_70 | **100%** | **1.00** | **0.78** |
| bm25_only | 100% | 0.90 | 0.74 |
| hybrid_default | 100% | 0.85 | 0.68 |
| vector_only | 100% | 0.85 | 0.62 |

Best document overall. All strategies achieved 100% hit rate. The 30/70 split achieved perfect MRR (1.0) — every query's top result was relevant.

### LLMLingua-2 (81 chunks, prompt compression paper)

| Strategy | Hit@5 | MRR | NDCG@5 |
|---|---|---|---|
| hybrid_50_50 | **100%** | **1.00** | **0.84** |
| hybrid_default | 100% | 1.00 | 0.82 |
| hybrid_30_70 | 100% | 1.00 | 0.82 |
| bm25_only | 100% | 0.90 | 0.72 |
| vector_only | 100% | 1.00 | 0.74 |

Only document where hybrid outperforms BM25. The vector signal helps here — likely because the chunks are semantically distinct enough that E5 embeddings add real value beyond keyword matching.

## 3. Per-Query Failure Analysis (hybrid default)

Only 1 query missed across all 15:

| Query | Doc | Hit | MRR | Issue |
|---|---|---|---|---|
| "How does DPR perform on out-of-domain datasets?" | RECOMP | miss | 0.00 | Vector retrieved general retrieval chunks instead of the specific DPR evaluation paragraph. BM25 found it via "DPR" + "out-of-domain" keywords. |

4 queries had low MRR (relevant result not in position 1):

| Query | MRR | Cause |
|---|---|---|
| "Training approach for extractive compressor" | 0.20 | Generic "training" matches too many chunks |
| "DPR on out-of-domain datasets" | 0.00 | Complete miss (vector-dominant failure) |
| "Extractive vs abstractive compression" | 0.33 | Related but wrong chunks ranked higher |
| "Challenges with long documents" | 0.25 | Very common topic across the paper |

**Pattern:** Failures cluster on queries with common/generic keywords ("training", "long documents"). BM25 handles specific entities ("DPR", "T5", "MeetingBank") well but generic queries benefit from vector semantics.

## 4. Enrichment Status

**None of the 20 ingested documents have enrichment data.** This means:

- No hypothetical questions exist, so `ingest eval <doc_id>` (synthetic eval) cannot run
- The concept index boost in hybrid search is empty — this feature is effectively disabled
- Chunk summaries are empty, so the summary embedding search path is unused
- Multi-embedding retrieval (content + summary + questions) reduces to single-embedding

The enrichment pipeline generates 3-5 hypothetical questions per chunk. These get embedded alongside the chunk content, creating additional retrieval vectors. Without enrichment, the system is running in a degraded mode.

## 5. Fixes Applied

### P0: Default fusion weights — DONE

Changed `vector_weight` from 0.7 to **0.4**, `bm25_weight` from 0.3 to **0.6** in `config.py`.

**Before/after on the same 15 queries:**

| Metric | Before (70/30) | After (40/60) | Change |
|---|---|---|---|
| avg Hit@5 | 93.3% | 93.3% | — |
| avg MRR | 0.786 | **0.867** | **+10.3%** |
| avg NDCG@5 | 0.637 | **0.758** | **+19.0%** |

### P2: CI quality gate — DONE

Added `tests/test_search_regression.py::TestSearchQualityGate` with 3 tests:
- `test_default_weights_meet_quality_bar` — ingests fixture, evals, asserts MRR >= 0.50, hit_rate >= 60%, NDCG >= 0.30
- `test_default_weights_are_bm25_dominant` — asserts `bm25_weight >= vector_weight`
- `test_weights_sum_close_to_one` — asserts weights sum to ~1.0

### P3: Exact-match term boost — DONE

Added `exact_match_boost` setting (default 0.003 per matching term). When >= 2 query terms appear verbatim in a chunk, that chunk gets a score bonus proportional to the number of matching terms. This helps proper nouns and acronyms (DPR, T5, GPT-4) that vector embeddings underweight.

Implementation in `search/hybrid.py`, tunable via `INGEST_EXACT_MATCH_BOOST` env var or `exact_match_boost` in config.

Tests in `tests/test_search_regression.py::TestExactMatchBoost`:
- `test_exact_match_boosts_entity_queries` — DPR-specific chunk ranks in top 2 for entity query
- `test_boost_disabled_when_zero` — setting boost=0 disables the feature completely
- `test_boost_requires_minimum_term_overlap` — single-term queries don't trigger boost

### P4: NDCG regression threshold — DONE

Added `assert report.mean_ndcg_at_k >= 0.30` to `test_retrieval_quality.py::test_topical_retrieval_hits`.

Current average across real documents is 0.758 with the new weights — well above the 0.30 floor.

## 6. Remaining Recommendations

### P1: Run enrichment on existing documents

The enrichment pipeline is the single biggest untested quality lever. Run enrichment on the 3 eval documents, then re-run this evaluation to measure the impact of:
- Hypothetical question embeddings (should improve recall for paraphrased queries)
- Concept index boost (should help entity-specific queries)
- Summary embeddings (should help broad/general queries)

Until enrichment runs on real documents, we can't know whether the pipeline justifies its LLM cost.

### P5: Evaluate cross-encoder reranking impact

The `reranker_model` setting is available but untested on real data. Set it to `cross-encoder/ms-marco-MiniLM-L-6-v2` and re-run this evaluation. The reranker should help with the failure cases where the right chunk was retrieved but ranked below position 1 (MRR < 1.0).

---

## Appendix: Raw Data

Full per-strategy, per-document, per-query results are in `docs/reports/eval_results.json`.

### Test Coverage Summary (as of this audit)

| Area | Test File | Tests | Status |
|---|---|---|---|
| Baseline regression | test_baseline_regression.py | 13 | all pass |
| Golden snapshot | test_golden_snapshot.py | 5 | all pass |
| Retrieval quality (mock) | test_retrieval_quality.py | 10 | all pass |
| Enrichment quality (mock) | test_enrichment_quality.py | 22 | all pass |
| Search quality bench (mock) | test_search_quality_bench.py | 2 | all pass |
| Search features | test_search_features.py | 6 | all pass |
| Search regression + exact boost | test_search_regression.py | 6 | all pass |
| Chunking quality | test_chunking_quality.py | 7 | all pass |
| Edge cases | test_edge_cases.py | 7 | all pass |
| Eval framework | test_eval.py | 8 | all pass |
| **Total quality tests** | | **86** | **all pass** |

### Gaps Remaining

- No test runs enrichment with a real LLM and measures output quality
- No test measures retrieval quality improvement from enrichment (before vs after)
- Cross-encoder reranker is tested for wiring (mock) but not for quality impact
- No latency/throughput benchmarks for search (only for chunking/storage)
