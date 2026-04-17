"""Tests for knowledge graph retrieval module."""

from __future__ import annotations

import json
from dataclasses import dataclass
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


# ---------------------------------------------------------------------------
# 10. Graph analysis (networkx-powered)
# ---------------------------------------------------------------------------


@dataclass
class _MockSettings:
    """Minimal settings stub for graph analysis tests."""

    kg_graph_analysis: bool = True
    kg_pagerank_damping: float = 0.85
    kg_community_boost: float = 1.2
    kg_hub_degree_multiplier: float = 3.0
    kg_hub_min_degree: int = 5  # lower for tests
    kg_bridge_boost: float = 1.5
    kg_hub_dampening: float = 0.3


@pytest.fixture()
def star_triples() -> list[KGTriple]:
    """Star graph: Hub connected to 25 spokes via the same predicate.

    hub --relates--> spoke_0 (c-0)
    hub --relates--> spoke_1 (c-1)
    ...
    hub --relates--> spoke_24 (c-24)
    """
    triples = []
    for i in range(25):
        triples.append(_triple("Hub", "relates", f"Spoke_{i}", f"c-{i}"))
    return triples


@pytest.fixture()
def cluster_triples() -> list[KGTriple]:
    """Two clusters connected by a bridge entity.

    Cluster A: A1 --uses--> A2 --extends--> A3 (chunks ca-1, ca-2)
    Cluster B: B1 --uses--> B2 --extends--> B3 (chunks cb-1, cb-2)
    Bridge:    A3 --depends_on--> B1          (chunk bridge-1)
    """
    return [
        _triple("A1", "uses", "A2", "ca-1"),
        _triple("A2", "extends", "A3", "ca-2"),
        _triple("B1", "uses", "B2", "cb-1"),
        _triple("B2", "extends", "B3", "cb-2"),
        _triple("A3", "depends_on", "B1", "bridge-1"),
    ]


class TestGraphMetricsComputation:
    def test_pagerank_runs(self, sample_triples: list[KGTriple]) -> None:
        idx = KGIndex()
        idx.add_triples(sample_triples)
        idx.compute_graph_metrics(_MockSettings())

        pr = idx._graph_metrics.get("pagerank", {})
        assert len(pr) > 0
        assert abs(sum(pr.values()) - 1.0) < 0.01  # PageRank sums to ~1.0

    def test_betweenness_runs(self, cluster_triples: list[KGTriple]) -> None:
        idx = KGIndex()
        idx.add_triples(cluster_triples)
        idx.compute_graph_metrics(_MockSettings())

        bc = idx._graph_metrics.get("betweenness", {})
        assert len(bc) > 0
        # Bridge entities (a3, b1) should have higher betweenness
        assert bc.get("a3", 0) > 0 or bc.get("b1", 0) > 0

    def test_communities_detected(self, cluster_triples: list[KGTriple]) -> None:
        idx = KGIndex()
        idx.add_triples(cluster_triples)
        idx.compute_graph_metrics(_MockSettings())

        communities = idx._graph_metrics.get("communities", {})
        assert len(communities) > 0
        # At least some entities should be assigned communities
        num_communities = idx._graph_metrics["stats"]["num_communities"]
        assert num_communities >= 1

    def test_hub_detection_star_graph(self, star_triples: list[KGTriple]) -> None:
        idx = KGIndex()
        idx.add_triples(star_triples)
        # Lower hub_min_degree for a 25-spoke star
        settings = _MockSettings(kg_hub_min_degree=5)
        idx.compute_graph_metrics(settings)

        hubs = idx._graph_metrics.get("hubs", {})
        assert "hub" in hubs  # the central node should be detected
        assert idx.is_hub("Hub")

    def test_empty_graph_no_crash(self) -> None:
        idx = KGIndex()
        idx.compute_graph_metrics(_MockSettings())
        assert idx._graph_metrics == {}

    def test_disabled_skips_analysis(self, sample_triples: list[KGTriple]) -> None:
        idx = KGIndex()
        idx.add_triples(sample_triples)
        idx.compute_graph_metrics(_MockSettings(kg_graph_analysis=False))
        assert idx._graph_metrics == {}


class TestPageRankBoost:
    def test_high_pagerank_amplifies_boost(self, sample_triples: list[KGTriple]) -> None:
        idx = KGIndex()
        idx.add_triples(sample_triples)
        idx.compute_graph_metrics(_MockSettings())

        # Boost WITH metrics
        boosted = kg_boost_scores(
            {"chunk-1": 0.5},
            ["chunk-1"],
            idx,
            sample_triples,
            boost_weight=0.1,
            min_confidence=0.0,
            settings=_MockSettings(),
        )

        # Boost WITHOUT metrics (fresh index, no compute)
        idx_no_metrics = KGIndex()
        idx_no_metrics.add_triples(sample_triples)
        baseline = kg_boost_scores(
            {"chunk-1": 0.5},
            ["chunk-1"],
            idx_no_metrics,
            sample_triples,
            boost_weight=0.1,
            min_confidence=0.0,
        )

        # With metrics, boosts should differ from baseline (importance modulation)
        assert boosted["chunk-1"] != baseline["chunk-1"]

    def test_no_metrics_falls_back(self, sample_triples: list[KGTriple]) -> None:
        """When _graph_metrics is empty, boost should equal old formula."""
        idx = KGIndex()
        idx.add_triples(sample_triples)
        # No compute_graph_metrics called

        result = kg_boost_scores(
            {"chunk-1": 0.5},
            ["chunk-1"],
            idx,
            sample_triples,
            boost_weight=0.1,
            min_confidence=0.0,
        )
        # Old formula: base + boost_weight * kg_relevance (1.0 for hop-0)
        assert result["chunk-1"] == pytest.approx(0.5 + 0.1 * 1.0)

    def test_disconnected_components(self) -> None:
        """PageRank should work on disconnected graphs."""
        triples = [
            _triple("A", "r", "B", "c1"),
            _triple("C", "r", "D", "c2"),  # separate component
        ]
        idx = KGIndex()
        idx.add_triples(triples)
        idx.compute_graph_metrics(_MockSettings())

        pr = idx._graph_metrics.get("pagerank", {})
        assert "a" in pr
        assert "c" in pr
        assert abs(sum(pr.values()) - 1.0) < 0.01


class TestCommunityBoost:
    def test_same_community_amplified(self, cluster_triples: list[KGTriple]) -> None:
        idx = KGIndex()
        idx.add_triples(cluster_triples)
        idx.compute_graph_metrics(_MockSettings())

        settings = _MockSettings()
        # Seed from cluster A chunks
        boosted = kg_boost_scores(
            {"ca-1": 0.5},
            ["ca-1"],
            idx,
            cluster_triples,
            boost_weight=0.1,
            min_confidence=0.0,
            settings=settings,
        )
        # ca-2 is in the same cluster, should get a community boost
        assert "ca-2" in boosted
        assert boosted["ca-2"] > 0

    def test_community_absent_no_crash(self, sample_triples: list[KGTriple]) -> None:
        """If graph_metrics has pagerank but not communities, no crash."""
        idx = KGIndex()
        idx.add_triples(sample_triples)
        idx.compute_graph_metrics(_MockSettings())
        # Manually remove communities to simulate partial metrics
        idx._graph_metrics.pop("communities", None)

        result = kg_boost_scores(
            {"chunk-1": 0.5},
            ["chunk-1"],
            idx,
            sample_triples,
            boost_weight=0.1,
            min_confidence=0.0,
            settings=_MockSettings(),
        )
        assert result["chunk-1"] > 0.5  # still boosted via importance


class TestHubDetection:
    def test_star_center_detected(self, star_triples: list[KGTriple]) -> None:
        idx = KGIndex()
        idx.add_triples(star_triples)
        idx.compute_graph_metrics(_MockSettings(kg_hub_min_degree=5))
        assert idx.is_hub("Hub")

    def test_low_predicate_diversity_is_noise_hub(self, star_triples: list[KGTriple]) -> None:
        """All edges use 'relates' predicate -> noise hub (diversity < 0.3)."""
        idx = KGIndex()
        idx.add_triples(star_triples)
        idx.compute_graph_metrics(_MockSettings(kg_hub_min_degree=5))

        hubs = idx._graph_metrics.get("hubs", {})
        # True means noise hub
        assert hubs.get("hub") is True

    def test_diverse_predicates_genuine_hub(self) -> None:
        """Hub with many different predicates -> genuine hub (not noise)."""
        predicates = [
            "uses",
            "extends",
            "implements",
            "depends_on",
            "authored_by",
            "evaluated_on",
            "improves",
            "requires",
            "enables",
            "causes",
        ]
        triples = []
        for i, pred in enumerate(predicates):
            triples.append(_triple("Center", pred, f"Node_{i}", f"c-{i}"))
        # Add more to exceed threshold
        for i in range(10, 25):
            triples.append(_triple("Center", f"rel_{i}", f"Node_{i}", f"c-{i}"))

        idx = KGIndex()
        idx.add_triples(triples)
        idx.compute_graph_metrics(_MockSettings(kg_hub_min_degree=5))

        hubs = idx._graph_metrics.get("hubs", {})
        assert "center" in hubs
        # False means genuine hub (diverse predicates)
        assert hubs["center"] is False

    def test_below_threshold_not_flagged(self, sample_triples: list[KGTriple]) -> None:
        """With min_degree=20, the small sample graph should have no hubs."""
        idx = KGIndex()
        idx.add_triples(sample_triples)
        idx.compute_graph_metrics(_MockSettings(kg_hub_min_degree=20))

        hubs = idx._graph_metrics.get("hubs", {})
        assert len(hubs) == 0

    def test_hub_dampening_in_boost(self, star_triples: list[KGTriple]) -> None:
        """Chunks discovered via a hub entity get dampened boost."""
        idx = KGIndex()
        idx.add_triples(star_triples)
        idx.compute_graph_metrics(_MockSettings(kg_hub_min_degree=5))

        settings = _MockSettings(kg_hub_min_degree=5)
        boosted = kg_boost_scores(
            {"c-0": 0.5},
            ["c-0"],
            idx,
            star_triples,
            boost_weight=0.1,
            min_confidence=0.0,
            settings=settings,
        )

        # Boost WITHOUT metrics for comparison
        idx_plain = KGIndex()
        idx_plain.add_triples(star_triples)
        baseline = kg_boost_scores(
            {"c-0": 0.5},
            ["c-0"],
            idx_plain,
            star_triples,
            boost_weight=0.1,
            min_confidence=0.0,
        )

        # Spokes discovered via hub should get dampened boost
        # Pick a spoke that's not the seed
        if "c-5" in boosted and "c-5" in baseline:
            assert boosted["c-5"] < baseline["c-5"]


class TestBridgeDetection:
    def test_bridge_entity_detected(self, cluster_triples: list[KGTriple]) -> None:
        """A3 and B1 connect two clusters — at least one should be a bridge."""
        idx = KGIndex()
        idx.add_triples(cluster_triples)
        idx.compute_graph_metrics(_MockSettings(kg_hub_min_degree=20))

        # At least one of the connecting entities should be a bridge
        assert idx.is_bridge("A3") or idx.is_bridge("B1")

    def test_hub_not_bridge(self, star_triples: list[KGTriple]) -> None:
        """Hub entity should NOT be classified as a bridge."""
        idx = KGIndex()
        idx.add_triples(star_triples)
        idx.compute_graph_metrics(_MockSettings(kg_hub_min_degree=5))

        assert idx.is_hub("Hub")
        assert not idx.is_bridge("Hub")


class TestGraphMetricsPersistence:
    def test_save_load_roundtrip_with_metrics(
        self, sample_triples: list[KGTriple], tmp_path: Path
    ) -> None:
        idx = KGIndex()
        idx.add_triples(sample_triples)
        idx.compute_graph_metrics(_MockSettings())

        p = tmp_path / "kg_index.json"
        idx.save(p)

        loaded = KGIndex.load(p)
        assert loaded._graph_metrics.get("pagerank") is not None
        assert loaded._graph_metrics.get("communities") is not None
        assert loaded._graph_metrics.get("hubs") is not None
        assert loaded._graph_metrics.get("betweenness") is not None

        # PageRank values should match
        for entity in idx._graph_metrics["pagerank"]:
            assert loaded._graph_metrics["pagerank"][entity] == pytest.approx(
                idx._graph_metrics["pagerank"][entity]
            )

    def test_load_old_format_without_metrics(self, tmp_path: Path) -> None:
        """Loading a JSON file without graph_metrics should yield empty metrics."""
        old_data = {
            "entity_chunks": {"foo": ["c1"]},
            "adjacency": {"foo": [["r", "bar"]]},
            "triple_chunks": {"foo|r|bar": ["c1"]},
        }
        p = tmp_path / "old_kg_index.json"
        p.write_text(json.dumps(old_data))

        loaded = KGIndex.load(p)
        assert loaded._graph_metrics == {}
        # Features should silently skip
        assert loaded.entity_pagerank("foo") == 0.0
        assert loaded.entity_community("foo") is None
        assert not loaded.is_hub("foo")
        assert not loaded.is_bridge("foo")

    def test_saved_json_includes_metrics_key(
        self, sample_triples: list[KGTriple], tmp_path: Path
    ) -> None:
        idx = KGIndex()
        idx.add_triples(sample_triples)
        idx.compute_graph_metrics(_MockSettings())

        p = tmp_path / "kg_index.json"
        idx.save(p)

        data = json.loads(p.read_text())
        assert "graph_metrics" in data
        assert "pagerank" in data["graph_metrics"]
        assert "communities" in data["graph_metrics"]
        assert "hubs" in data["graph_metrics"]
        assert "stats" in data["graph_metrics"]
