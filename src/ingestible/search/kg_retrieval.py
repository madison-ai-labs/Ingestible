"""Knowledge graph-powered retrieval.

Builds an in-memory graph from KG triples extracted during enrichment and uses
entity relationships to discover chunks that are topically related but might not
share surface-level vocabulary with the query.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ingestible.models.chunks import ChunkSet
from ingestible.models.enrichment import KGTriple

logger = logging.getLogger(__name__)


def _normalize(entity: str) -> str:
    """Lower-case, strip whitespace."""
    return entity.strip().lower()


class KGIndex:
    """In-memory knowledge graph index for entity-based retrieval.

    Builds a graph from KG triples and supports:
    - Entity lookup: find chunks mentioning an entity
    - Neighbor expansion: find chunks related to entities in matched chunks
    - Path traversal: follow relationship chains (1-2 hops)
    """

    def __init__(self) -> None:
        # entity_name (normalized) -> set of chunk_ids
        self._entity_chunks: dict[str, set[str]] = defaultdict(set)
        # entity_name -> set of (predicate, related_entity)
        self._adjacency: dict[str, set[tuple[str, str]]] = defaultdict(set)
        # (entity, predicate, entity) -> set of chunk_ids (provenance)
        self._triple_chunks: dict[tuple[str, str, str], set[str]] = defaultdict(set)
        # Keep track of all indexed triples for confidence lookups
        self._triples: list[KGTriple] = []
        # Precomputed graph metrics (pagerank, betweenness, communities, hubs)
        self._graph_metrics: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Building
    # ------------------------------------------------------------------

    def add_triples(self, triples: list[KGTriple]) -> None:
        """Index a batch of triples."""
        for t in triples:
            subj = _normalize(t.subject)
            obj = _normalize(t.object)
            pred = _normalize(t.predicate)

            if not subj or not obj:
                continue

            chunk_id = t.source_chunk_id

            # Entity -> chunk mapping
            if chunk_id:
                self._entity_chunks[subj].add(chunk_id)
                self._entity_chunks[obj].add(chunk_id)

            # Adjacency (bidirectional)
            self._adjacency[subj].add((pred, obj))
            self._adjacency[obj].add((pred, subj))

            # Triple provenance
            triple_key = (subj, pred, obj)
            if chunk_id:
                self._triple_chunks[triple_key].add(chunk_id)

            self._triples.append(t)

    # ------------------------------------------------------------------
    # Querying
    # ------------------------------------------------------------------

    def entity_chunks(self, entity: str) -> set[str]:
        """Get chunk IDs that mention this entity."""
        return set(self._entity_chunks.get(_normalize(entity), set()))

    def expand_from_chunks(
        self,
        seed_chunk_ids: list[str],
        all_triples: list[KGTriple],
        max_hops: int = 1,
        min_confidence: float = 0.5,
    ) -> dict[str, float]:
        """Given seed chunks from search results, find related chunks via KG traversal.

        Returns: dict of chunk_id -> relevance_score (decays with hop distance)
        - Hop 0 (direct entity match): 1.0
        - Hop 1 (one relationship away): 0.5
        - Hop 2 (two relationships away): 0.25
        """
        # Build a quick confidence lookup from all_triples
        triple_confidence: dict[tuple[str, str, str], float] = {}
        for t in all_triples:
            key = (_normalize(t.subject), _normalize(t.predicate), _normalize(t.object))
            # Keep the highest confidence if duplicates exist
            triple_confidence[key] = max(triple_confidence.get(key, 0.0), t.confidence)

        seed_set = set(seed_chunk_ids)
        result: dict[str, float] = {}

        # Collect entities that appear in the seed chunks
        seed_entities: set[str] = set()
        for entity, chunk_ids in self._entity_chunks.items():
            if chunk_ids & seed_set:
                seed_entities.add(entity)

        # Hop 0: chunks directly associated with seed entities
        for entity in seed_entities:
            for cid in self._entity_chunks.get(entity, set()):
                if cid not in result or result[cid] < 1.0:
                    result[cid] = 1.0

        # BFS expansion
        current_frontier = seed_entities
        visited_entities: set[str] = set(seed_entities)

        for hop in range(1, max_hops + 1):
            decay = 1.0 / (2**hop)  # 0.5, 0.25, ...
            next_frontier: set[str] = set()

            for entity in current_frontier:
                for pred, neighbor in self._adjacency.get(entity, set()):
                    if neighbor in visited_entities:
                        continue

                    # Check confidence of the edge in both directions
                    fwd_key = (entity, pred, neighbor)
                    rev_key = (neighbor, pred, entity)
                    conf = max(
                        triple_confidence.get(fwd_key, 0.0),
                        triple_confidence.get(rev_key, 0.0),
                    )
                    if conf < min_confidence:
                        continue

                    next_frontier.add(neighbor)

                    # Score the chunks reachable via this neighbor
                    for cid in self._entity_chunks.get(neighbor, set()):
                        if cid not in result or result[cid] < decay:
                            result[cid] = decay

            visited_entities |= next_frontier
            current_frontier = next_frontier

        return result

    def query_entities(self, query: str, min_entity_length: int = 3) -> list[str]:
        """Extract potential entity mentions from a query string.

        Simple approach: check which indexed entities appear as substrings
        in the query (case-insensitive). Returns entities sorted longest-first
        to prefer more specific matches.

        Entities shorter than min_entity_length are skipped to avoid
        false positives from common short strings.
        """
        q_lower = query.lower()
        matches: list[str] = []
        for entity in self._entity_chunks:
            if len(entity) < min_entity_length:
                continue
            if entity in q_lower:
                matches.append(entity)
        # Longest first — more specific entities take priority
        matches.sort(key=len, reverse=True)
        return matches

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, path: Path) -> None:
        """Persist index to JSON."""
        data: dict[str, Any] = {
            "entity_chunks": {k: sorted(v) for k, v in self._entity_chunks.items()},
            "adjacency": {k: sorted(v) for k, v in self._adjacency.items()},
            "triple_chunks": {
                f"{s}|{p}|{o}": sorted(cids) for (s, p, o), cids in self._triple_chunks.items()
            },
        }
        if self._graph_metrics:
            data["graph_metrics"] = self._graph_metrics
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
        logger.debug("Saved KG index to %s (%d entities)", path, len(self._entity_chunks))

    @classmethod
    def load(cls, path: Path) -> KGIndex:
        """Load index from JSON."""
        idx = cls()
        raw = json.loads(path.read_text())

        for entity, cids in raw.get("entity_chunks", {}).items():
            idx._entity_chunks[entity] = set(cids)

        for entity, neighbors in raw.get("adjacency", {}).items():
            idx._adjacency[entity] = {(pred, nbr) for pred, nbr in neighbors}

        for triple_key_str, cids in raw.get("triple_chunks", {}).items():
            parts = triple_key_str.split("|", 2)
            if len(parts) == 3:
                idx._triple_chunks[(parts[0], parts[1], parts[2])] = set(cids)

        idx._graph_metrics = raw.get("graph_metrics", {})

        logger.debug("Loaded KG index from %s (%d entities)", path, len(idx._entity_chunks))
        return idx

    @classmethod
    def from_chunks(cls, chunks: ChunkSet) -> KGIndex:
        """Build index from a ChunkSet's knowledge graph triples."""
        idx = cls()
        idx.add_triples(chunks.knowledge_graph)
        # Also pick up triples stored directly on L3 chunks
        for l3 in chunks.l3_chunks:
            idx.add_triples(l3.kg_triples)
        return idx

    # ------------------------------------------------------------------
    # Graph analysis (networkx-powered)
    # ------------------------------------------------------------------

    def _build_nx_graph(self):  # noqa: ANN201 — returns nx.Graph
        """Build a networkx graph from the adjacency structure."""
        import networkx as nx

        G = nx.Graph()
        # Build edge confidence lookup from triples
        edge_confidence: dict[tuple[str, str], float] = {}
        for t in self._triples:
            subj, obj = _normalize(t.subject), _normalize(t.object)
            if not subj or not obj:
                continue
            pair = (min(subj, obj), max(subj, obj))
            edge_confidence[pair] = max(edge_confidence.get(pair, 0.0), t.confidence)

        for entity, neighbors in self._adjacency.items():
            for _pred, neighbor in neighbors:
                pair = (min(entity, neighbor), max(entity, neighbor))
                weight = edge_confidence.get(pair, 1.0)
                if G.has_edge(entity, neighbor):
                    G[entity][neighbor]["weight"] = max(G[entity][neighbor]["weight"], weight)
                else:
                    G.add_edge(entity, neighbor, weight=weight)

        return G

    def compute_graph_metrics(self, settings) -> None:
        """Compute graph-theoretic metrics for entity importance and clustering.

        Called at index build time (stage5). Results are stored in
        ``_graph_metrics`` and persisted via ``save()``.

        Args:
            settings: A ``Settings`` instance (or anything with the
                ``kg_graph_analysis``, ``kg_pagerank_damping``,
                ``kg_hub_degree_multiplier``, and ``kg_hub_min_degree`` attrs).
        """
        if not getattr(settings, "kg_graph_analysis", False):
            return
        if len(self._entity_chunks) < 3:
            logger.debug("KG too small for graph analysis (%d entities)", len(self._entity_chunks))
            return

        import networkx as nx

        G = self._build_nx_graph()
        if G.number_of_nodes() < 3:
            return

        metrics: dict[str, Any] = {"stats": {}}

        # --- PageRank ---
        damping = getattr(settings, "kg_pagerank_damping", 0.85)
        metrics["pagerank"] = nx.pagerank(G, alpha=damping, weight="weight")

        # --- Betweenness centrality (skip for very large graphs) ---
        if G.number_of_nodes() <= 50_000:
            metrics["betweenness"] = nx.betweenness_centrality(G, weight="weight")
        else:
            logger.warning(
                "Skipping betweenness centrality: %d nodes exceeds 50k limit",
                G.number_of_nodes(),
            )
            metrics["betweenness"] = {}

        # --- Community detection (Louvain) ---
        communities = nx.community.louvain_communities(G, weight="weight", seed=42)
        community_map: dict[str, int] = {}
        for cid, community in enumerate(communities):
            for entity in community:
                community_map[entity] = cid
        metrics["communities"] = community_map
        metrics["stats"]["num_communities"] = len(communities)

        # --- Hub detection ---
        degrees = dict(G.degree())
        avg_degree = sum(degrees.values()) / max(len(degrees), 1)
        hub_multiplier = getattr(settings, "kg_hub_degree_multiplier", 3.0)
        hub_min = getattr(settings, "kg_hub_min_degree", 20)
        hub_threshold = max(avg_degree * hub_multiplier, hub_min)

        hubs: dict[str, bool] = {}  # entity -> is_noise_hub
        for entity, degree in degrees.items():
            if degree >= hub_threshold:
                # Check predicate diversity: many different predicates = genuine hub
                unique_preds = len({pred for pred, _ in self._adjacency.get(entity, set())})
                diversity = unique_preds / max(degree, 1)
                hubs[entity] = diversity < 0.3  # True = noise hub, False = genuine hub
        metrics["hubs"] = hubs
        metrics["stats"]["avg_degree"] = round(avg_degree, 2)
        metrics["stats"]["hub_threshold"] = round(hub_threshold, 2)
        metrics["stats"]["num_hubs"] = len(hubs)

        self._graph_metrics = metrics
        logger.info(
            "KG graph analysis: %d nodes, %d communities, %d hubs (avg degree %.1f)",
            G.number_of_nodes(),
            len(communities),
            len(hubs),
            avg_degree,
        )

    # --- Metric accessors ---

    def entity_pagerank(self, entity: str) -> float:
        """Return the PageRank score for *entity*, or 0.0 if unavailable."""
        pr = self._graph_metrics.get("pagerank", {})
        return pr.get(_normalize(entity), 0.0)

    def entity_community(self, entity: str) -> int | None:
        """Return the community ID for *entity*, or ``None``."""
        cm = self._graph_metrics.get("communities", {})
        return cm.get(_normalize(entity))

    def is_hub(self, entity: str) -> bool:
        """Return whether *entity* was detected as a hub (noise or genuine)."""
        return _normalize(entity) in self._graph_metrics.get("hubs", {})

    def is_bridge(self, entity: str) -> bool:
        """High betweenness centrality AND not a hub."""
        norm = _normalize(entity)
        if norm in self._graph_metrics.get("hubs", {}):
            return False
        bc = self._graph_metrics.get("betweenness", {})
        if not bc:
            return False
        avg_bc = sum(bc.values()) / max(len(bc), 1)
        return bc.get(norm, 0.0) > avg_bc


# ----------------------------------------------------------------------
# Integration helper
# ----------------------------------------------------------------------


def kg_boost_scores(
    scores: dict[str, float],
    seed_chunk_ids: list[str],
    kg_index: KGIndex,
    all_triples: list[KGTriple],
    boost_weight: float = 0.01,
    max_hops: int = 1,
    min_confidence: float = 0.5,
    settings=None,
) -> dict[str, float]:
    """Apply KG-based score boosts to existing search scores.

    Finds chunks related to top results via KG traversal and adds
    a small boost to their scores. Also adds scores for previously
    unseen chunks discovered through the KG.

    When the KG index has precomputed graph metrics (PageRank,
    communities, hub detection), boosts are modulated by entity
    importance, topic coherence, and hub dampening.

    Args:
        scores: Current chunk_id -> score mapping from RRF.
        seed_chunk_ids: Top-N chunk IDs to expand from.
        kg_index: The KG index.
        all_triples: All triples for provenance/confidence lookup.
        boost_weight: Maximum boost to add (scales with hop proximity).
        max_hops: How many relationship hops to traverse.
        min_confidence: Minimum triple confidence to follow.
        settings: Optional ``Settings`` for graph analysis knobs.

    Returns:
        Updated scores dict with KG boosts applied.
    """
    kg_scores = kg_index.expand_from_chunks(
        seed_chunk_ids,
        all_triples,
        max_hops=max_hops,
        min_confidence=min_confidence,
    )

    has_metrics = bool(kg_index._graph_metrics.get("pagerank"))

    # Precompute seed entity communities for community coherence scoring
    seed_communities: set[int] = set()
    if has_metrics:
        seed_set = set(seed_chunk_ids)
        for entity, chunk_ids in kg_index._entity_chunks.items():
            if chunk_ids & seed_set:
                comm = kg_index.entity_community(entity)
                if comm is not None:
                    seed_communities.add(comm)

    # Build a reverse mapping: chunk_id -> entities (for discovered chunks)
    chunk_entities: dict[str, list[str]] = defaultdict(list)
    if has_metrics:
        for entity, chunk_ids in kg_index._entity_chunks.items():
            for cid in chunk_ids:
                if cid in kg_scores:
                    chunk_entities[cid].append(entity)

    # Read config knobs
    community_boost_mult = getattr(settings, "kg_community_boost", 1.2) if settings else 1.2
    bridge_boost_mult = getattr(settings, "kg_bridge_boost", 1.5) if settings else 1.5
    hub_dampening_mult = getattr(settings, "kg_hub_dampening", 0.3) if settings else 0.3

    # Compute PageRank normalization range for mapping to [0.5, 2.0]
    pr_min, pr_max = 0.0, 0.0
    if has_metrics:
        pr_values = list(kg_index._graph_metrics["pagerank"].values())
        if pr_values:
            pr_min, pr_max = min(pr_values), max(pr_values)

    boosted = dict(scores)
    for cid, kg_relevance in kg_scores.items():
        if not has_metrics:
            boost = boost_weight * kg_relevance
            boosted[cid] = boosted.get(cid, 0.0) + boost
            continue

        entities = chunk_entities.get(cid, [])

        # --- Importance factor (PageRank) ---
        if entities and pr_max > pr_min:
            best_pr = max(kg_index.entity_pagerank(e) for e in entities)
            # Normalize to [0.5, 2.0]
            importance = 0.5 + 1.5 * (best_pr - pr_min) / (pr_max - pr_min)
        else:
            importance = 1.0

        # --- Community coherence ---
        if entities and seed_communities:
            chunk_comms = {kg_index.entity_community(e) for e in entities} - {None}
            if chunk_comms & seed_communities:
                community = community_boost_mult
            else:
                community = 1.0 / community_boost_mult
        else:
            community = 1.0

        # --- Hub dampening / bridge boost ---
        hub_factor = 1.0
        if entities:
            for e in entities:
                if kg_index.is_hub(e):
                    hub_factor = min(hub_factor, hub_dampening_mult)
                elif kg_index.is_bridge(e):
                    hub_factor = max(hub_factor, bridge_boost_mult)

        boost = boost_weight * kg_relevance * importance * community * hub_factor
        boosted[cid] = boosted.get(cid, 0.0) + boost

    return boosted


# ----------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------


@dataclass
class KGRetrievalConfig:
    """Configuration for knowledge-graph-powered retrieval."""

    enabled: bool = False
    boost_weight: float = 0.01
    max_hops: int = 1
    min_confidence: float = 0.5
    seed_top_n: int = 10  # how many top results to use as seeds
