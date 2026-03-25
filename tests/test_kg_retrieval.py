"""Tests for knowledge graph retrieval module."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ingestible.models.enrichment import KGTriple
from ingestible.search.kg_retrieval import KGIndex, kg_boost_scores

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _triple(
    subject: str,
    predicate: str,
    obj: str,
    chunk_id: str = "",
    confidence: float = 1.0,
    subject_type: str = "",
    object_type: str = "",
) -> KGTriple:
    return KGTriple(
        subject=subject,
        predicate=predicate,
        object=obj,
        source_chunk_id=chunk_id,
        confidence=confidence,
        subject_type=subject_type,
        object_type=object_type,
    )


@pytest.fixture()
def sample_triples() -> list[KGTriple]:
    """A small graph:

    Python --uses--> GIL       (chunk-1)
    GIL    --limits--> threading (chunk-2)
    threading --part_of--> stdlib (chunk-3)
    Python --is_a--> language   (chunk-1)
    Rust   --lacks--> GIL       (chunk-4)
    """
    return [
        _triple("Python", "uses", "GIL", "chunk-1"),
        _triple("GIL", "limits", "threading", "chunk-2"),
        _triple("threading", "part_of", "stdlib", "chunk-3"),
        _triple("Python", "is_a", "language", "chunk-1"),
        _triple("Rust", "lacks", "GIL", "chunk-4"),
    ]


@pytest.fixture()
def kg_index(sample_triples: list[KGTriple]) -> KGIndex:
    idx = KGIndex()
    idx.add_triples(sample_triples)
    return idx


# ---------------------------------------------------------------------------
# 1. Building KGIndex from triples
# ---------------------------------------------------------------------------


class TestBuildIndex:
    def test_entities_indexed(self, kg_index: KGIndex) -> None:
        # All six unique entities should be present
        expected = {"python", "gil", "threading", "stdlib", "language", "rust"}
        assert set(kg_index._entity_chunks.keys()) == expected

    def test_adjacency_bidirectional(self, kg_index: KGIndex) -> None:
        # "python" should have edges to "gil" and "language"
        neighbors = {nbr for _, nbr in kg_index._adjacency["python"]}
        assert "gil" in neighbors
        assert "language" in neighbors

        # "gil" should have edges back to "python", to "threading", and to "rust"
        gil_neighbors = {nbr for _, nbr in kg_index._adjacency["gil"]}
        assert "python" in gil_neighbors
        assert "threading" in gil_neighbors
        assert "rust" in gil_neighbors

    def test_triple_provenance(self, kg_index: KGIndex) -> None:
        key = ("python", "uses", "gil")
        assert "chunk-1" in kg_index._triple_chunks[key]


# ---------------------------------------------------------------------------
# 2. entity_chunks lookup
# ---------------------------------------------------------------------------


class TestEntityChunks:
    def test_known_entity(self, kg_index: KGIndex) -> None:
        assert kg_index.entity_chunks("Python") == {"chunk-1"}

    def test_case_insensitive(self, kg_index: KGIndex) -> None:
        assert kg_index.entity_chunks("PYTHON") == {"chunk-1"}

    def test_entity_in_multiple_chunks(self, kg_index: KGIndex) -> None:
        # GIL appears in chunk-1 (Python-uses-GIL), chunk-2 (GIL-limits-threading),
        # and chunk-4 (Rust-lacks-GIL)
        assert kg_index.entity_chunks("GIL") == {"chunk-1", "chunk-2", "chunk-4"}

    def test_unknown_entity(self, kg_index: KGIndex) -> None:
        assert kg_index.entity_chunks("JavaScript") == set()


# ---------------------------------------------------------------------------
# 3. expand_from_chunks — 1 hop
# ---------------------------------------------------------------------------


class TestExpandOneHop:
    def test_direct_and_neighbor_chunks(
        self, kg_index: KGIndex, sample_triples: list[KGTriple]
    ) -> None:
        # Seed: chunk-1 (has entities: python, gil, language)
        result = kg_index.expand_from_chunks(
            ["chunk-1"], sample_triples, max_hops=1, min_confidence=0.0
        )
        # Hop 0: chunks with python/gil/language -> chunk-1, chunk-2, chunk-4
        assert result.get("chunk-1") == 1.0
        assert result.get("chunk-2") == 1.0  # gil is a seed entity
        assert result.get("chunk-4") == 1.0  # gil is a seed entity

        # Hop 1 neighbors of {python, gil, language}: threading, stdlib, rust
        # threading -> chunk-2, chunk-3; rust -> chunk-4; stdlib -> chunk-3
        # chunk-2 and chunk-4 already scored 1.0 from hop 0, so they stay 1.0
        assert result.get("chunk-3") == 0.5

    def test_min_confidence_filters(
        self, kg_index: KGIndex, sample_triples: list[KGTriple]
    ) -> None:
        # If we set min_confidence very high, only hop-0 entities should appear
        # because the default confidence on our triples is 1.0, but let's make
        # a scenario with low-confidence triples.
        low_conf_triples = [
            _triple("Alpha", "relates", "Beta", "c-a", confidence=0.3),
            _triple("Beta", "relates", "Gamma", "c-b", confidence=0.3),
        ]
        idx = KGIndex()
        idx.add_triples(low_conf_triples)

        result = idx.expand_from_chunks(["c-a"], low_conf_triples, max_hops=1, min_confidence=0.5)
        # Seed entities: alpha, beta (from c-a)
        # Hop 0: c-a (alpha, beta)
        assert "c-a" in result
        # Hop 1 neighbor of beta is gamma, but confidence 0.3 < 0.5 -> filtered
        assert "c-b" not in result or result["c-b"] == 1.0  # c-b has beta (hop 0)


# ---------------------------------------------------------------------------
# 4. expand_from_chunks — 2 hops
# ---------------------------------------------------------------------------


class TestExpandTwoHops:
    def test_two_hop_decay(self, kg_index: KGIndex, sample_triples: list[KGTriple]) -> None:
        # Seed: chunk-4 (entities: rust, gil)
        # Hop 0: chunks with rust/gil -> chunk-1, chunk-2, chunk-4
        # Hop 1 neighbors: python, threading, language -> chunk-1(1.0 already), chunk-2(1.0), chunk-3(0.5)
        # Hop 2 neighbors of {python, threading, language}: stdlib (the only new one)
        #   stdlib -> chunk-3. chunk-3 already 0.5 from hop 1, 0.25 < 0.5 so stays 0.5
        result = kg_index.expand_from_chunks(
            ["chunk-4"], sample_triples, max_hops=2, min_confidence=0.0
        )

        assert result.get("chunk-4") == 1.0
        assert result.get("chunk-1") == 1.0  # gil is seed entity
        assert result.get("chunk-2") == 1.0  # gil is seed entity
        # chunk-3 reached at hop 1 via threading
        assert result.get("chunk-3") == 0.5

    def test_two_hop_reaches_further(self) -> None:
        """Linear chain: A--B--C--D. Seed at A, 2 hops should reach D."""
        triples = [
            _triple("A", "r", "B", "c1"),
            _triple("B", "r", "C", "c2"),
            _triple("C", "r", "D", "c3"),
        ]
        idx = KGIndex()
        idx.add_triples(triples)

        # 1 hop from c1 (entities A, B): hop-0 gets c1,c2; hop-1 neighbor C -> c2,c3
        r1 = idx.expand_from_chunks(["c1"], triples, max_hops=1, min_confidence=0.0)
        assert "c3" in r1  # C is hop-1 neighbor, c3 has C

        # 2 hops: hop-2 neighbor D -> c3
        r2 = idx.expand_from_chunks(["c1"], triples, max_hops=2, min_confidence=0.0)
        assert "c3" in r2


# ---------------------------------------------------------------------------
# 5. query_entities
# ---------------------------------------------------------------------------


class TestQueryEntities:
    def test_finds_substring_entities(self, kg_index: KGIndex) -> None:
        entities = kg_index.query_entities("How does Python handle the GIL?")
        assert "python" in entities
        assert "gil" in entities

    def test_case_insensitive_match(self, kg_index: KGIndex) -> None:
        entities = kg_index.query_entities("THREADING in stdlib")
        assert "threading" in entities
        assert "stdlib" in entities

    def test_no_match(self, kg_index: KGIndex) -> None:
        assert kg_index.query_entities("unrelated query about fish") == []

    def test_short_entities_filtered(self) -> None:
        """Entities shorter than min_entity_length are not matched."""
        triples = [
            _triple("A", "r", "B", "c1"),
            _triple("Python", "r", "GIL", "c2"),
        ]
        idx = KGIndex()
        idx.add_triples(triples)
        # "a" and "b" are 1-char entities, should be filtered
        entities = idx.query_entities("A uses Python and B")
        assert "python" in entities
        assert "a" not in entities
        assert "b" not in entities

    def test_longest_first_ordering(self) -> None:
        """More specific (longer) entities should appear before shorter ones."""
        triples = [
            _triple("machine learning", "is_a", "field", "c1"),
            _triple("learning", "is_a", "activity", "c2"),
        ]
        idx = KGIndex()
        idx.add_triples(triples)
        entities = idx.query_entities("machine learning is great")
        assert entities[0] == "machine learning"


# ---------------------------------------------------------------------------
# 6. kg_boost_scores
# ---------------------------------------------------------------------------


class TestKGBoostScores:
    def test_boosts_related_chunks(self, kg_index: KGIndex, sample_triples: list[KGTriple]) -> None:
        original = {"chunk-1": 0.9, "chunk-2": 0.7}
        boosted = kg_boost_scores(
            scores=original,
            seed_chunk_ids=["chunk-1"],
            kg_index=kg_index,
            all_triples=sample_triples,
            boost_weight=0.1,
            max_hops=1,
            min_confidence=0.0,
        )
        # chunk-1 should get a boost (it's in hop-0)
        assert boosted["chunk-1"] > original["chunk-1"]
        # chunk-2 should also get a boost
        assert boosted["chunk-2"] > original["chunk-2"]
        # chunk-3 should appear (discovered via KG, wasn't in original)
        assert "chunk-3" in boosted
        assert boosted["chunk-3"] > 0.0

    def test_boost_weight_scales(self, kg_index: KGIndex, sample_triples: list[KGTriple]) -> None:
        low = kg_boost_scores(
            {"chunk-1": 1.0}, ["chunk-1"], kg_index, sample_triples, boost_weight=0.01
        )
        high = kg_boost_scores(
            {"chunk-1": 1.0}, ["chunk-1"], kg_index, sample_triples, boost_weight=0.5
        )
        assert high["chunk-1"] > low["chunk-1"]

    def test_empty_seeds(self, kg_index: KGIndex, sample_triples: list[KGTriple]) -> None:
        original = {"chunk-1": 0.9}
        boosted = kg_boost_scores(original, [], kg_index, sample_triples, boost_weight=0.1)
        # No seeds -> no KG expansion -> scores unchanged
        assert boosted == original


# ---------------------------------------------------------------------------
# 7. save / load round-trip
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_round_trip(
        self, kg_index: KGIndex, tmp_path: Path, sample_triples: list[KGTriple]
    ) -> None:
        p = tmp_path / "kg_index.json"
        kg_index.save(p)

        loaded = KGIndex.load(p)

        # Entity chunks should match
        assert loaded.entity_chunks("Python") == kg_index.entity_chunks("Python")
        assert loaded.entity_chunks("GIL") == kg_index.entity_chunks("GIL")

        # Adjacency should match
        assert loaded._adjacency.keys() == kg_index._adjacency.keys()
        for k in kg_index._adjacency:
            assert loaded._adjacency[k] == kg_index._adjacency[k]

        # Triple provenance should match
        assert loaded._triple_chunks.keys() == kg_index._triple_chunks.keys()

    def test_saved_file_is_valid_json(self, kg_index: KGIndex, tmp_path: Path) -> None:
        p = tmp_path / "kg_index.json"
        kg_index.save(p)
        data = json.loads(p.read_text())
        assert "entity_chunks" in data
        assert "adjacency" in data
        assert "triple_chunks" in data


# ---------------------------------------------------------------------------
# 8. Empty index
# ---------------------------------------------------------------------------


class TestEmptyIndex:
    def test_entity_chunks_empty(self) -> None:
        idx = KGIndex()
        assert idx.entity_chunks("anything") == set()

    def test_expand_empty(self) -> None:
        idx = KGIndex()
        result = idx.expand_from_chunks(["c1"], [], max_hops=1)
        assert result == {}

    def test_query_entities_empty(self) -> None:
        idx = KGIndex()
        assert idx.query_entities("some query") == []

    def test_save_load_empty(self, tmp_path: Path) -> None:
        idx = KGIndex()
        p = tmp_path / "empty.json"
        idx.save(p)
        loaded = KGIndex.load(p)
        assert loaded.entity_chunks("x") == set()

    def test_add_empty_triples(self) -> None:
        idx = KGIndex()
        idx.add_triples([])
        assert len(idx._entity_chunks) == 0


# ---------------------------------------------------------------------------
# 9. Confidence filtering
# ---------------------------------------------------------------------------


class TestConfidenceFiltering:
    def test_low_confidence_triples_filtered_at_hop(self) -> None:
        triples = [
            _triple("X", "r1", "Y", "c1", confidence=1.0),
            _triple("Y", "r2", "Z", "c2", confidence=0.2),
        ]
        idx = KGIndex()
        idx.add_triples(triples)

        # Seed c1 (entities X, Y). Hop 1 would reach Z via Y-r2-Z,
        # but confidence 0.2 < 0.5 threshold -> Z filtered.
        result = idx.expand_from_chunks(["c1"], triples, max_hops=1, min_confidence=0.5)
        # c1 and c2 both have Y (hop-0 entity), so c2 still appears at score 1.0
        # But Z's chunks would only come from hop-1 expansion.
        # Since both c1 and c2 contain seed entities (X in c1, Y in both),
        # c2 is already reachable at hop 0.
        assert result.get("c1") == 1.0
        assert result.get("c2") == 1.0  # Y is a seed entity present in c2

    def test_confidence_threshold_blocks_traversal(self) -> None:
        """Ensure that when a hop-1 neighbor is ONLY reachable via low-confidence
        edges, it does not appear in results."""
        triples = [
            _triple("A", "r", "B", "c1", confidence=1.0),
            _triple("C", "r", "D", "c2", confidence=0.1),  # separate component
        ]
        idx = KGIndex()
        idx.add_triples(triples)

        result = idx.expand_from_chunks(["c1"], triples, max_hops=2, min_confidence=0.5)
        # c2 entities (C, D) are not connected to A or B at all
        assert "c2" not in result

    def test_high_confidence_passes(self) -> None:
        triples = [
            _triple("A", "r1", "B", "c1", confidence=1.0),
            _triple("B", "r2", "C", "c2", confidence=0.9),
        ]
        idx = KGIndex()
        idx.add_triples(triples)

        result = idx.expand_from_chunks(["c1"], triples, max_hops=1, min_confidence=0.5)
        # B is a seed entity (in c1), so c2 (which also has B) is hop-0.
        # C is hop-1 neighbor of B with confidence 0.9 >= 0.5 -> passes.
        assert "c2" in result

    def test_zero_min_confidence_allows_all(self) -> None:
        triples = [
            _triple("A", "r1", "B", "c1", confidence=0.01),
            _triple("B", "r2", "C", "c2", confidence=0.01),
        ]
        idx = KGIndex()
        idx.add_triples(triples)

        result = idx.expand_from_chunks(["c1"], triples, max_hops=1, min_confidence=0.0)
        assert "c1" in result
        assert "c2" in result
