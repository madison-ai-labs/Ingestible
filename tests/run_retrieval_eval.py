#!/usr/bin/env python3
"""Retrieval quality evaluation against real ingested documents.

Runs manual Q&A queries against 3 documents, compares hybrid/vector/BM25,
tests weight variations, and outputs results as JSON for the report.

Run: .venv/bin/python tests/run_retrieval_eval.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ingestible.config import Settings
from ingestible.eval import EvalQuery, evaluate_document

# ---------------------------------------------------------------------------
# Manual Q&A pairs (hand-crafted from reading actual chunk content)
# ---------------------------------------------------------------------------

EVAL_SETS: dict[str, dict] = {
    "recomp_2310.04408-b788867b880a": {
        "label": "RECOMP (prompt compression)",
        "queries": [
            EvalQuery(
                query="How does extractive compression differ from abstractive compression?",
                expected_chunk_ids=[],  # will be auto-matched
            ),
            EvalQuery(
                query="What is the training approach for the extractive compressor?",
                expected_chunk_ids=[],
            ),
            EvalQuery(
                query="How does DPR perform on out-of-domain datasets?",
                expected_chunk_ids=[],
            ),
            EvalQuery(
                query="What compression ratio does the T5 summarization model achieve?",
                expected_chunk_ids=[],
            ),
            EvalQuery(
                query="How does prepending retrieved documents affect language model inference cost?",
                expected_chunk_ids=[],
            ),
        ],
    },
    "selectivecontext_2310.06201-39bcba21f823": {
        "label": "Selective Context (self-information filtering)",
        "queries": [
            EvalQuery(
                query="What is self-information in the context of language modeling?",
                expected_chunk_ids=[],
            ),
            EvalQuery(
                query="How does the percentile-based filtering approach work for selecting lexical units?",
                expected_chunk_ids=[],
            ),
            EvalQuery(
                query="What model is used to compute self-information for the LLaMA family?",
                expected_chunk_ids=[],
            ),
            EvalQuery(
                query="How much CUDA memory does the original context require compared to selective context?",
                expected_chunk_ids=[],
            ),
            EvalQuery(
                query="What challenges do LLMs face with long documents and extended conversations?",
                expected_chunk_ids=[],
            ),
        ],
    },
    "llmlingua-2_2403.12968-0fc7eb960768": {
        "label": "LLMLingua-2 (prompt compression)",
        "queries": [
            EvalQuery(
                query="How was the MeetingBank QA dataset constructed?",
                expected_chunk_ids=[],
            ),
            EvalQuery(
                query="How does LLMLingua-2 perform on Chinese benchmarks despite English-only training?",
                expected_chunk_ids=[],
            ),
            EvalQuery(
                query="What evaluation metric is used for the QA task?",
                expected_chunk_ids=[],
            ),
            EvalQuery(
                query="What is the difference between task-aware and task-agnostic compression?",
                expected_chunk_ids=[],
            ),
            EvalQuery(
                query="What is the summarization evaluation metric used in LLMLingua-2?",
                expected_chunk_ids=[],
            ),
        ],
    },
}


def _match_queries_to_chunks(doc_id: str, queries: list[EvalQuery], settings: Settings):
    """Auto-match queries to chunk IDs by keyword overlap (BM25-style).

    Since we don't have ground-truth chunk IDs, we use keyword matching
    to find the most relevant chunks for each query and treat those as
    the expected results.
    """
    from ingestible.pipeline.stage6_storage import load_chunks

    chunks = load_chunks(settings.documents_dir / doc_id)

    for q in queries:
        query_words = set(q.query.lower().split())
        # Score each chunk by word overlap
        scored = []
        for c in chunks.l3_chunks:
            content_words = set(c.content.lower().split())
            overlap = len(query_words & content_words)
            if overlap >= 2:  # at least 2 words in common
                scored.append((c.chunk_id, overlap))

        # Take top 3 by overlap
        scored.sort(key=lambda x: x[1], reverse=True)
        q.expected_chunk_ids = [cid for cid, _ in scored[:3]]

    # Filter queries that got no matches (bad queries)
    return [q for q in queries if q.expected_chunk_ids]


def run_eval():
    settings = Settings()
    results = {}

    for doc_id, eval_set in EVAL_SETS.items():
        doc_dir = settings.documents_dir / doc_id
        if not doc_dir.exists():
            print(f"SKIP {eval_set['label']}: document not found")
            continue

        print(f"\n{'='*72}")
        print(f"Evaluating: {eval_set['label']} ({doc_id})")
        print(f"{'='*72}")

        queries = _match_queries_to_chunks(doc_id, eval_set["queries"], settings)
        if not queries:
            print("  No matched queries — skipping")
            continue

        print(f"  Matched {len(queries)}/{len(eval_set['queries'])} queries to chunks")

        doc_results = {"label": eval_set["label"], "doc_id": doc_id, "strategies": {}}

        # --- Strategy comparison ---
        weight_configs = {
            "hybrid_default": {"vector_weight": 0.7, "bm25_weight": 0.3},
            "vector_only": {"vector_weight": 1.0, "bm25_weight": 0.0},
            "bm25_only": {"vector_weight": 0.0, "bm25_weight": 1.0},
            "hybrid_50_50": {"vector_weight": 0.5, "bm25_weight": 0.5},
            "hybrid_30_70": {"vector_weight": 0.3, "bm25_weight": 0.7},
            "hybrid_80_20": {"vector_weight": 0.8, "bm25_weight": 0.2},
        }

        print(f"\n  {'Strategy':<20} {'Hit@5':>8} {'MRR':>8} {'P@5':>8} {'R@5':>8} {'NDCG@5':>8}")
        print(f"  {'-'*60}")

        for name, weights in weight_configs.items():
            s = settings.model_copy(update=weights)
            try:
                report = evaluate_document(doc_id, s, queries=queries, k=5)
                doc_results["strategies"][name] = report.to_dict()
                print(
                    f"  {name:<20} {report.hit_rate:>8.1%} {report.mrr:>8.4f} "
                    f"{report.mean_precision_at_k:>8.4f} {report.mean_recall_at_k:>8.4f} "
                    f"{report.mean_ndcg_at_k:>8.4f}"
                )
            except Exception as e:
                print(f"  {name:<20} ERROR: {e}")
                doc_results["strategies"][name] = {"error": str(e)}

        # --- Per-query breakdown for default hybrid ---
        try:
            default_report = evaluate_document(doc_id, settings, queries=queries, k=5)
            print("\n  Per-query breakdown (hybrid default):")
            for r in default_report.results:
                hit_marker = "✓" if r.hit else "✗"
                print(f"    {hit_marker} MRR={r.reciprocal_rank:.2f} NDCG={r.ndcg_at_k:.2f}  {r.query[:60]}")
                if not r.hit:
                    print(f"      Expected: {r.expected_chunk_ids[:2]}")
                    print(f"      Got:      {r.retrieved_chunk_ids[:3]}")
        except Exception as e:
            print(f"  Per-query breakdown failed: {e}")

        results[doc_id] = doc_results

    # --- Aggregate cross-document summary ---
    print(f"\n{'='*72}")
    print("CROSS-DOCUMENT SUMMARY")
    print(f"{'='*72}")

    for strategy in ["hybrid_default", "vector_only", "bm25_only", "hybrid_50_50", "hybrid_30_70", "hybrid_80_20"]:
        hit_rates = []
        mrrs = []
        ndcgs = []
        for doc_id, doc_results in results.items():
            s = doc_results["strategies"].get(strategy, {})
            if "error" not in s and "hit_rate" in s:
                hit_rates.append(s["hit_rate"])
                mrrs.append(s["mrr"])
                ndcgs.append(s["mean_ndcg_at_k"])

        if hit_rates:
            avg_hit = sum(hit_rates) / len(hit_rates)
            avg_mrr = sum(mrrs) / len(mrrs)
            avg_ndcg = sum(ndcgs) / len(ndcgs)
            print(f"  {strategy:<20} avg_hit={avg_hit:.1%}  avg_MRR={avg_mrr:.4f}  avg_NDCG={avg_ndcg:.4f}")

    # Save raw results
    out_path = Path(__file__).parent.parent / "docs" / "reports" / "eval_results.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, indent=2) + "\n")
    print(f"\nResults saved to {out_path}")


if __name__ == "__main__":
    run_eval()
