"""Tests for the retrieval evaluation framework."""

import json

from ingestible.eval import (
    EvalQuery,
    EvalReport,
    _generate_synthetic_queries,
    load_eval_queries,
)
from ingestible.models.chunks import ChunkSet, L0Chunk, L3Chunk


class TestEvalQuery:
    def test_create(self):
        eq = EvalQuery(query="What is X?", expected_chunk_ids=["c1", "c2"])
        assert eq.query == "What is X?"
        assert len(eq.expected_chunk_ids) == 2


class TestSyntheticQueries:
    def test_generates_from_hypothetical_questions(self):
        chunks = ChunkSet(
            doc_id="test",
            l0=L0Chunk(chunk_id="test-L0", title="Test"),
            l3_chunks=[
                L3Chunk(
                    chunk_id="c1",
                    content="Some content",
                    hypothetical_questions=["What is X?", "How does Y work?"],
                ),
                L3Chunk(
                    chunk_id="c2",
                    content="Other content",
                    hypothetical_questions=["Why is Z important?"],
                ),
            ],
        )
        queries = _generate_synthetic_queries(chunks)
        assert len(queries) == 3
        assert queries[0].query == "What is X?"
        assert queries[0].expected_chunk_ids == ["c1"]
        assert queries[2].query == "Why is Z important?"
        assert queries[2].expected_chunk_ids == ["c2"]

    def test_no_questions_returns_empty(self):
        chunks = ChunkSet(
            doc_id="test",
            l0=L0Chunk(chunk_id="test-L0", title="Test"),
            l3_chunks=[
                L3Chunk(chunk_id="c1", content="No questions here"),
            ],
        )
        queries = _generate_synthetic_queries(chunks)
        assert queries == []


class TestLoadEvalQueries:
    def test_load_jsonl(self, tmp_path):
        f = tmp_path / "queries.jsonl"
        f.write_text(
            json.dumps({"query": "What is X?", "expected_chunk_ids": ["c1"]})
            + "\n"
            + json.dumps({"query": "How does Y?", "expected_chunk_ids": ["c2", "c3"]})
            + "\n"
        )
        queries = load_eval_queries(f)
        assert len(queries) == 2
        assert queries[0].query == "What is X?"
        assert queries[1].expected_chunk_ids == ["c2", "c3"]

    def test_load_empty_file(self, tmp_path):
        f = tmp_path / "empty.jsonl"
        f.write_text("")
        queries = load_eval_queries(f)
        assert queries == []


class TestEvalReport:
    def test_summary_format(self):
        report = EvalReport(
            doc_id="test-doc",
            total_queries=10,
            k=5,
            hit_rate=0.8,
            mrr=0.65,
            mean_precision_at_k=0.3,
            mean_recall_at_k=0.7,
        )
        summary = report.summary()
        assert "test-doc" in summary
        assert "80.0%" in summary
        assert "0.6500" in summary

    def test_to_dict(self):
        report = EvalReport(
            doc_id="test-doc",
            total_queries=5,
            k=3,
            hit_rate=0.6,
            mrr=0.5,
            mean_precision_at_k=0.2,
            mean_recall_at_k=0.4,
        )
        d = report.to_dict()
        assert d["doc_id"] == "test-doc"
        assert d["hit_rate"] == 0.6
        assert d["mrr"] == 0.5


class TestDoclingChunker:
    """Test the docling chunking strategy."""

    def test_heading_forces_chunk_boundary(self):
        from ingestible.config import Settings
        from ingestible.pipeline.stage3_chunking import _split_into_passages

        text = (
            "# Introduction\n\n"
            "Some intro text with enough words to avoid being merged as a runt chunk.\n\n"
            "# Methods\n\n"
            "Some methods text with enough words to avoid being merged as a runt chunk."
        )
        settings = Settings(
            chunking_strategy="docling",
            max_chunk_tokens=500,
            min_chunk_tokens=5,
        )
        chunks = _split_into_passages(text, "doc", "ch", "sec", settings)
        assert len(chunks) == 2
        assert "Introduction" in chunks[0].content
        assert "Methods" in chunks[1].content
