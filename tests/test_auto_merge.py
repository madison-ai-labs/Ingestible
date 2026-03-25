"""Tests for auto-merge retrieval logic."""

from ingestible.models.chunks import (
    ChunkSet,
    L0Chunk,
    L1Chunk,
    L2Chunk,
    L3Chunk,
)
from ingestible.models.search import SearchResult
from ingestible.search.auto_merge import AutoMergeConfig, auto_merge_results


def _make_chunk_set() -> ChunkSet:
    """Build a minimal ChunkSet with two chapters, each with two sections,
    each with three passages."""
    l0 = L0Chunk(chunk_id="doc-l0", title="Test Doc")

    l1a = L1Chunk(
        chunk_id="ch1",
        title="Chapter 1",
        content="Chapter 1 overview.",
        chapter_summary="Summary of ch1",
        children_ids=["sec1", "sec2"],
    )
    l1b = L1Chunk(
        chunk_id="ch2",
        title="Chapter 2",
        content="Chapter 2 overview.",
        chapter_summary="Summary of ch2",
        children_ids=["sec3", "sec4"],
    )

    l2_sec1 = L2Chunk(
        chunk_id="sec1",
        title="Section 1",
        content="Full section 1 content.",
        section_summary="Section 1 summary",
        parent_chapter_id="ch1",
        children_ids=["p1", "p2", "p3"],
    )
    l2_sec2 = L2Chunk(
        chunk_id="sec2",
        title="Section 2",
        content="Full section 2 content.",
        section_summary="Section 2 summary",
        parent_chapter_id="ch1",
        children_ids=["p4", "p5", "p6"],
    )
    l2_sec3 = L2Chunk(
        chunk_id="sec3",
        title="Section 3",
        content="Full section 3 content.",
        section_summary="Section 3 summary",
        parent_chapter_id="ch2",
        children_ids=["p7", "p8", "p9"],
    )
    l2_sec4 = L2Chunk(
        chunk_id="sec4",
        title="Section 4",
        content="Full section 4 content.",
        section_summary="Section 4 summary",
        parent_chapter_id="ch2",
        children_ids=["p10", "p11", "p12"],
    )

    def _passages(ids, parent):
        return [
            L3Chunk(
                chunk_id=cid,
                content=f"Passage {cid} text.",
                parent_section_id=parent,
            )
            for cid in ids
        ]

    l3s = (
        _passages(["p1", "p2", "p3"], "sec1")
        + _passages(["p4", "p5", "p6"], "sec2")
        + _passages(["p7", "p8", "p9"], "sec3")
        + _passages(["p10", "p11", "p12"], "sec4")
    )

    return ChunkSet(
        doc_id="test-doc",
        l0=l0,
        l1_chunks=[l1a, l1b],
        l2_chunks=[l2_sec1, l2_sec2, l2_sec3, l2_sec4],
        l3_chunks=l3s,
    )


def _result(chunk_id: str, score: float, sources: list[str] | None = None) -> SearchResult:
    return SearchResult(
        chunk_id=chunk_id,
        content=f"Content of {chunk_id}",
        score=score,
        match_sources=sources or ["vector"],
    )


# ---------- Tests ----------


class TestNoMerging:
    def test_below_threshold(self):
        """Two L3s from sec1 — below default threshold of 3, no merge."""
        cs = _make_chunk_set()
        results = [_result("p1", 0.9), _result("p2", 0.8)]
        config = AutoMergeConfig(enabled=True, merge_threshold=3)

        merged = auto_merge_results(results, cs, config)

        ids = [r.chunk_id for r in merged]
        assert ids == ["p1", "p2"]
        assert all("auto_merged" not in r.match_sources for r in merged)

    def test_disabled_config_is_passthrough(self):
        """When enabled=False the results come back unchanged."""
        cs = _make_chunk_set()
        results = [_result("p1", 0.9), _result("p2", 0.8), _result("p3", 0.7)]
        config = AutoMergeConfig(enabled=False)

        merged = auto_merge_results(results, cs, config)
        assert merged is results  # identity — no copy

    def test_none_config_is_passthrough(self):
        cs = _make_chunk_set()
        results = [_result("p1", 0.9)]
        merged = auto_merge_results(results, cs, None)
        assert merged is results


class TestMerging:
    def test_merge_when_threshold_met(self):
        """Three L3s from sec1 — should collapse to one L2 result."""
        cs = _make_chunk_set()
        results = [_result("p1", 0.9), _result("p2", 0.8), _result("p3", 0.7)]
        config = AutoMergeConfig(enabled=True, merge_threshold=3)

        merged = auto_merge_results(results, cs, config)

        assert len(merged) == 1
        r = merged[0]
        assert r.chunk_id == "sec1"
        assert r.content == "Full section 1 content."
        assert r.section == "Section 1"
        assert r.chapter == "Chapter 1"
        assert "auto_merged" in r.match_sources

    def test_score_preservation(self):
        """Merged result must carry the max score of its constituents."""
        cs = _make_chunk_set()
        results = [_result("p1", 0.6), _result("p2", 0.95), _result("p3", 0.4)]
        config = AutoMergeConfig(enabled=True, merge_threshold=3)

        merged = auto_merge_results(results, cs, config)
        assert merged[0].score == 0.95

    def test_match_sources_aggregated(self):
        """Match sources from all constituents are collected."""
        cs = _make_chunk_set()
        results = [
            _result("p1", 0.9, ["vector"]),
            _result("p2", 0.8, ["bm25"]),
            _result("p3", 0.7, ["vector", "concept"]),
        ]
        config = AutoMergeConfig(enabled=True, merge_threshold=3)

        merged = auto_merge_results(results, cs, config)
        sources = set(merged[0].match_sources)
        assert sources == {"vector", "bm25", "concept", "auto_merged"}

    def test_summary_from_l2(self):
        """Merged result carries the L2 section_summary."""
        cs = _make_chunk_set()
        results = [_result("p1", 0.9), _result("p2", 0.8), _result("p3", 0.7)]
        config = AutoMergeConfig(enabled=True, merge_threshold=3)

        merged = auto_merge_results(results, cs, config)
        assert merged[0].summary == "Section 1 summary"


class TestMixedResults:
    def test_partial_merge(self):
        """sec1 hits threshold (3 L3s), sec2 does not (2 L3s). Non-merged stay."""
        cs = _make_chunk_set()
        results = [
            _result("p1", 0.9),
            _result("p2", 0.85),
            _result("p3", 0.8),
            _result("p4", 0.75),
            _result("p5", 0.7),
        ]
        config = AutoMergeConfig(enabled=True, merge_threshold=3)

        merged = auto_merge_results(results, cs, config)

        ids = [r.chunk_id for r in merged]
        # sec1 merged, p4/p5 kept individually
        assert "sec1" in ids
        assert "p4" in ids
        assert "p5" in ids
        assert len(merged) == 3  # 1 merged + 2 individual
        # Sorted by score descending
        assert merged[0].chunk_id == "sec1"  # max 0.9
        assert merged[0].score == 0.9

    def test_non_l3_results_untouched(self):
        """Results whose chunk_id isn't an L3 pass through untouched."""
        cs = _make_chunk_set()
        results = [
            _result("sec2", 0.85),  # already an L2
            _result("p1", 0.9),
            _result("p2", 0.8),
            _result("p3", 0.7),
        ]
        config = AutoMergeConfig(enabled=True, merge_threshold=3)

        merged = auto_merge_results(results, cs, config)
        ids = [r.chunk_id for r in merged]
        # Original sec2 result kept, plus sec1 from merged L3s
        assert "sec2" in ids
        assert "sec1" in ids
        assert len(merged) == 2


class TestL1Merging:
    def test_prefer_l1_merges_l2s_up(self):
        """With prefer_l1, after L3→L2, multiple L2s from same L1 merge to L1."""
        cs = _make_chunk_set()
        # 3 L3s from sec1 and 3 from sec2 — both under ch1
        results = [
            _result("p1", 0.9),
            _result("p2", 0.85),
            _result("p3", 0.8),
            _result("p4", 0.75),
            _result("p5", 0.7),
            _result("p6", 0.65),
        ]
        config = AutoMergeConfig(enabled=True, merge_threshold=3, prefer_l1=True)

        merged = auto_merge_results(results, cs, config)

        # First pass: p1-p3 → sec1, p4-p6 → sec2
        # Second pass: sec1 + sec2 are 2, threshold is 3 → no L1 merge
        # So we still have 2 L2 results
        assert len(merged) == 2
        ids = {r.chunk_id for r in merged}
        assert ids == {"sec1", "sec2"}

    def test_prefer_l1_with_lower_threshold(self):
        """With threshold=2, two L2s from ch1 merge to L1."""
        cs = _make_chunk_set()
        results = [
            _result("p1", 0.9),
            _result("p2", 0.85),
            _result("p4", 0.75),
            _result("p5", 0.7),
        ]
        config = AutoMergeConfig(enabled=True, merge_threshold=2, prefer_l1=True)

        merged = auto_merge_results(results, cs, config)

        assert len(merged) == 1
        r = merged[0]
        assert r.chunk_id == "ch1"
        assert r.content == "Chapter 1 overview."
        assert r.summary == "Summary of ch1"
        assert r.chapter == "Chapter 1"
        assert "auto_merged" in r.match_sources
        assert r.score == 0.9


class TestEmptyResults:
    def test_empty_list(self):
        cs = _make_chunk_set()
        config = AutoMergeConfig(enabled=True)
        merged = auto_merge_results([], cs, config)
        assert merged == []

    def test_empty_list_disabled(self):
        cs = _make_chunk_set()
        merged = auto_merge_results([], cs)
        assert merged == []
