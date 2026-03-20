"""Concept → chunk_ids JSON index.

For "tell me everything about X" queries.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from pathlib import Path

logger = logging.getLogger(__name__)


class ConceptIndex:
    def __init__(self):
        self._index: dict[str, list[str]] = defaultdict(list)

    def add(self, concept: str, chunk_id: str) -> None:
        normalized = concept.lower().strip()
        if normalized and chunk_id not in self._index[normalized]:
            self._index[normalized].append(chunk_id)

    def add_many(self, concepts: list[str], chunk_id: str) -> None:
        for concept in concepts:
            self.add(concept, chunk_id)

    def lookup(self, query: str) -> list[str]:
        """Find chunk_ids matching any concept that equals or contains the query as a whole word."""
        q = query.lower().strip()
        if not q:
            return []
        results: set[str] = set()
        q_words = set(q.split())
        for concept, chunk_ids in self._index.items():
            # Exact match or query words are a subset of concept words
            concept_words = set(concept.split())
            if q == concept or q_words <= concept_words:
                results.update(chunk_ids)
        return list(results)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(dict(self._index), indent=2), encoding="utf-8")
        logger.info("Concept index saved to %s (%d concepts)", path, len(self._index))

    @classmethod
    def load(cls, path: Path) -> ConceptIndex:
        idx = cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        idx._index = defaultdict(list, data)
        return idx

    @property
    def count(self) -> int:
        return len(self._index)
