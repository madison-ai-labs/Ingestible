"""Retrieval evaluation framework.

Measures retrieval quality using Q&A pairs against ingested documents.
Can use synthetic queries from LLM-generated hypothetical questions,
or manual Q&A pairs from a JSONL file.

Metrics: Precision@K, Recall@K, MRR (Mean Reciprocal Rank), Hit Rate@K.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from ingestible.config import Settings
from ingestible.pipeline.stage5_embedding import Embedder
from ingestible.pipeline.stage6_storage import load_chunks
from ingestible.search.hybrid import load_searcher

logger = logging.getLogger(__name__)


@dataclass
class EvalQuery:
    """A single evaluation query with expected chunk IDs."""
    query: str
    expected_chunk_ids: list[str]
    metadata: dict = field(default_factory=dict)


@dataclass
class EvalResult:
    """Result of evaluating a single query."""
    query: str
    expected_chunk_ids: list[str]
    retrieved_chunk_ids: list[str]
    hit: bool  # any expected chunk in top-K
    reciprocal_rank: float  # 1/rank of first relevant result (0 if none)
    precision_at_k: float
    recall_at_k: float


@dataclass
class EvalReport:
    """Aggregate evaluation metrics across all queries."""
    doc_id: str
    total_queries: int
    k: int
    hit_rate: float  # fraction of queries with at least one relevant result in top-K
    mrr: float  # mean reciprocal rank
    mean_precision_at_k: float
    mean_recall_at_k: float
    results: list[EvalResult] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "doc_id": self.doc_id,
            "total_queries": self.total_queries,
            "k": self.k,
            "hit_rate": round(self.hit_rate, 4),
            "mrr": round(self.mrr, 4),
            "mean_precision_at_k": round(self.mean_precision_at_k, 4),
            "mean_recall_at_k": round(self.mean_recall_at_k, 4),
        }

    def summary(self) -> str:
        lines = [
            f"Eval: {self.doc_id} — {self.total_queries} queries @ K={self.k}",
            f"  Hit Rate@{self.k}:     {self.hit_rate:.1%}",
            f"  MRR:                {self.mrr:.4f}",
            f"  Precision@{self.k}:    {self.mean_precision_at_k:.4f}",
            f"  Recall@{self.k}:       {self.mean_recall_at_k:.4f}",
        ]
        return "\n".join(lines)


def evaluate_document(
    doc_id: str,
    settings: Settings,
    queries: list[EvalQuery] | None = None,
    k: int = 5,
) -> EvalReport:
    """Evaluate retrieval quality for a document.

    If no queries are provided, generates synthetic queries from
    the hypothetical questions in enriched L3 chunks.

    Args:
        doc_id: Document to evaluate
        settings: Ingestible settings
        queries: Manual Q&A pairs (optional — uses synthetic if None)
        k: Number of results to retrieve per query

    Returns:
        EvalReport with aggregate metrics and per-query results
    """
    doc_dir = settings.documents_dir / doc_id
    if not doc_dir.exists():
        raise FileNotFoundError(f"Document not found: {doc_id}")

    chunks = load_chunks(doc_dir)
    embedder = Embedder(settings)
    searcher = load_searcher(doc_dir, chunks, embedder, settings)

    # Generate synthetic queries if none provided
    if queries is None:
        queries = _generate_synthetic_queries(chunks)
        if not queries:
            raise ValueError(
                f"No hypothetical questions found in {doc_id}. "
                "Run enrichment first, or provide manual Q&A pairs."
            )

    logger.info("Evaluating %d queries against %s @ K=%d", len(queries), doc_id, k)

    results: list[EvalResult] = []
    for eq in queries:
        response = searcher.search(eq.query, n_results=k)
        retrieved_ids = [r.chunk_id for r in response.results]

        # Compute metrics
        expected_set = set(eq.expected_chunk_ids)
        hits_in_retrieved = [cid for cid in retrieved_ids if cid in expected_set]

        hit = len(hits_in_retrieved) > 0

        # Reciprocal rank: 1/position of first relevant result
        rr = 0.0
        for i, cid in enumerate(retrieved_ids):
            if cid in expected_set:
                rr = 1.0 / (i + 1)
                break

        # Precision@K: relevant retrieved / K
        precision = len(hits_in_retrieved) / len(retrieved_ids) if retrieved_ids else 0.0

        # Recall@K: relevant retrieved / total relevant
        recall = len(hits_in_retrieved) / len(expected_set) if expected_set else 0.0

        results.append(EvalResult(
            query=eq.query,
            expected_chunk_ids=eq.expected_chunk_ids,
            retrieved_chunk_ids=retrieved_ids,
            hit=hit,
            reciprocal_rank=rr,
            precision_at_k=precision,
            recall_at_k=recall,
        ))

    # Aggregate
    n = len(results)
    hit_rate = sum(1 for r in results if r.hit) / n if n > 0 else 0.0
    mrr = sum(r.reciprocal_rank for r in results) / n if n > 0 else 0.0
    mean_precision = sum(r.precision_at_k for r in results) / n if n > 0 else 0.0
    mean_recall = sum(r.recall_at_k for r in results) / n if n > 0 else 0.0

    return EvalReport(
        doc_id=doc_id,
        total_queries=n,
        k=k,
        hit_rate=hit_rate,
        mrr=mrr,
        mean_precision_at_k=mean_precision,
        mean_recall_at_k=mean_recall,
        results=results,
    )


def _generate_synthetic_queries(chunks) -> list[EvalQuery]:
    """Generate eval queries from enrichment hypothetical questions.

    Each hypothetical question should retrieve the chunk it came from.
    This is a self-consistency check: if the pipeline generated the question
    from chunk X, searching for that question should return chunk X.
    """
    queries: list[EvalQuery] = []
    for chunk in chunks.l3_chunks:
        for q in chunk.hypothetical_questions:
            queries.append(EvalQuery(
                query=q,
                expected_chunk_ids=[chunk.chunk_id],
                metadata={"source": "synthetic", "source_chunk": chunk.chunk_id},
            ))
    return queries


def load_eval_queries(path: Path) -> list[EvalQuery]:
    """Load evaluation queries from a JSONL file.

    Each line: {"query": "...", "expected_chunk_ids": ["chunk1", "chunk2"]}
    """
    queries: list[EvalQuery] = []
    for line in path.read_text(encoding="utf-8").strip().split("\n"):
        if not line.strip():
            continue
        data = json.loads(line)
        queries.append(EvalQuery(
            query=data["query"],
            expected_chunk_ids=data.get("expected_chunk_ids", []),
            metadata=data.get("metadata", {}),
        ))
    return queries


def compare_strategies(
    doc_id: str,
    settings: Settings,
    queries: list[EvalQuery] | None = None,
    k: int = 5,
) -> dict[str, EvalReport]:
    """Compare retrieval with different settings (e.g., enriched vs not).

    Returns a dict mapping strategy name to EvalReport.
    Currently compares: full search vs vector-only vs BM25-only.
    """
    doc_dir = settings.documents_dir / doc_id
    chunks = load_chunks(doc_dir)
    embedder = Embedder(settings)

    if queries is None:
        queries = _generate_synthetic_queries(chunks)

    reports: dict[str, EvalReport] = {}

    # Full hybrid search (default)
    reports["hybrid"] = evaluate_document(doc_id, settings, queries, k)

    # Vector-only (set BM25 weight to 0)
    vector_settings = settings.model_copy(update={"bm25_weight": 0.0, "vector_weight": 1.0})
    reports["vector_only"] = evaluate_document(doc_id, vector_settings, queries, k)

    # BM25-only (set vector weight to 0)
    bm25_settings = settings.model_copy(update={"vector_weight": 0.0, "bm25_weight": 1.0})
    reports["bm25_only"] = evaluate_document(doc_id, bm25_settings, queries, k)

    return reports
