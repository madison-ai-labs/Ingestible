"""ChromaDB vector store wrapper.

Stores multiple embeddings per chunk (content, summary, hypothetical questions).
Deduplicates by chunk_id at query time.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Sequence

import chromadb

logger = logging.getLogger(__name__)

BATCH_SIZE = 500


class VectorStore:
    def __init__(
        self,
        persist_dir: Path,
        collection_name: str = "chunks",
        distance_metric: str = "cosine",
    ):
        self._client = chromadb.PersistentClient(path=str(persist_dir))
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": distance_metric},
        )

    def add_embeddings(
        self,
        ids: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict],
        documents: list[str] | None = None,
    ) -> None:
        """Add embeddings in batches of BATCH_SIZE."""
        for start in range(0, len(ids), BATCH_SIZE):
            end = start + BATCH_SIZE
            batch_ids = ids[start:end]
            batch_embs = embeddings[start:end]
            batch_meta = metadatas[start:end]
            kwargs: dict = {
                "ids": batch_ids,
                "embeddings": batch_embs,
                "metadatas": batch_meta,
            }
            if documents:
                kwargs["documents"] = documents[start:end]
            self._collection.add(**kwargs)

    def query(
        self,
        query_embedding: list[float],
        n_results: int = 20,
        where: dict | None = None,
    ) -> list[tuple[str, float, dict]]:
        """Query the vector store. Returns (chunk_id, distance, metadata) tuples,
        deduplicated by chunk_id (keeps best score)."""
        kwargs: dict = {
            "query_embeddings": [query_embedding],
            "n_results": n_results,
        }
        if where:
            kwargs["where"] = where

        results = self._collection.query(**kwargs)

        # Deduplicate by chunk_id — keep the best (lowest distance) per chunk
        seen: dict[str, tuple[float, dict]] = {}
        if results["ids"] and results["ids"][0]:
            ids = results["ids"][0]
            distances = results["distances"][0] if results["distances"] else [0.0] * len(ids)
            metadatas = results["metadatas"][0] if results["metadatas"] else [{}] * len(ids)

            for emb_id, dist, meta in zip(ids, distances, metadatas):
                chunk_id = meta.get("chunk_id", emb_id)
                if chunk_id not in seen or dist < seen[chunk_id][0]:
                    seen[chunk_id] = (dist, meta)

        return [(cid, dist, meta) for cid, (dist, meta) in seen.items()]

    @property
    def count(self) -> int:
        return self._collection.count()
