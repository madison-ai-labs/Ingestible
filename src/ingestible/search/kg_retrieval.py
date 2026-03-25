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
        data = {
            "entity_chunks": {k: sorted(v) for k, v in self._entity_chunks.items()},
            "adjacency": {k: sorted(v) for k, v in self._adjacency.items()},
            "triple_chunks": {
                f"{s}|{p}|{o}": sorted(cids) for (s, p, o), cids in self._triple_chunks.items()
            },
        }
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
) -> dict[str, float]:
    """Apply KG-based score boosts to existing search scores.

    Finds chunks related to top results via KG traversal and adds
    a small boost to their scores. Also adds scores for previously
    unseen chunks discovered through the KG.

    Args:
        scores: Current chunk_id -> score mapping from RRF.
        seed_chunk_ids: Top-N chunk IDs to expand from.
        kg_index: The KG index.
        all_triples: All triples for provenance/confidence lookup.
        boost_weight: Maximum boost to add (scales with hop proximity).
        max_hops: How many relationship hops to traverse.
        min_confidence: Minimum triple confidence to follow.

    Returns:
        Updated scores dict with KG boosts applied.
    """
    kg_scores = kg_index.expand_from_chunks(
        seed_chunk_ids,
        all_triples,
        max_hops=max_hops,
        min_confidence=min_confidence,
    )

    boosted = dict(scores)
    for cid, kg_relevance in kg_scores.items():
        boost = boost_weight * kg_relevance
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
