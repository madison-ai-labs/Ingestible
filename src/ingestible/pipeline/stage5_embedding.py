"""Stage 5 — Embedding & Indexing.

Uses sentence-transformers (E5-large-v2) for embeddings.
Builds: ChromaDB vector index, BM25 sparse index, concept index.

E5 models require prefixes:
  - "passage: " for documents
  - "query: " for queries
"""

from __future__ import annotations

import logging
from pathlib import Path

from sentence_transformers import SentenceTransformer

from ingestible.config import Settings
from ingestible.models.chunks import ChunkSet, L3Chunk
from ingestible.search.bm25_store import BM25Store
from ingestible.search.concept_index import ConceptIndex
from ingestible.search.vector_store import VectorStore

logger = logging.getLogger(__name__)


def _resolve_device(device: str) -> str:
    """Resolve 'auto' to the best available device."""
    if device != "auto":
        return device

    import torch
    if torch.cuda.is_available():
        return "cuda"
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


class Embedder:
    """Manages the embedding model and index creation."""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._model: SentenceTransformer | None = None

    @property
    def model(self) -> SentenceTransformer:
        if self._model is None:
            logger.info("Loading embedding model: %s", self._settings.embedding_model)
            device = _resolve_device(self._settings.embedding_device)
            logger.info("Embedding device: %s", device)
            self._model = SentenceTransformer(
                self._settings.embedding_model,
                device=device,
            )
        return self._model

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        """Embed passage texts with the 'passage: ' prefix."""
        prefixed = [f"passage: {t}" for t in texts]
        embeddings = self.model.encode(
            prefixed, normalize_embeddings=True, show_progress_bar=True
        )
        result = embeddings.tolist()
        return [self._post_process(v) for v in result]

    def embed_query(self, query: str) -> list[float]:
        """Embed a query with the 'query: ' prefix."""
        embedding = self.model.encode(
            f"query: {query}", normalize_embeddings=True
        )
        return self._post_process(embedding.tolist())

    def _post_process(self, vector: list[float]) -> list[float]:
        """Apply Matryoshka truncation and/or binary quantization."""
        dims = self._settings.embedding_dimensions
        if dims is not None and dims < len(vector):
            vector = vector[:dims]
            # Re-normalize after truncation
            import math
            norm = math.sqrt(sum(x * x for x in vector))
            if norm > 0:
                vector = [x / norm for x in vector]

        if self._settings.embedding_quantization == "binary":
            vector = [1.0 if x >= 0 else 0.0 for x in vector]

        return vector


def build_indexes(
    chunks: ChunkSet,
    doc_dir: Path,
    embedder: Embedder,
    language: str = "en",
    previous_chunks: ChunkSet | None = None,
) -> tuple[VectorStore, BM25Store, ConceptIndex]:
    """Build all search indexes for a document.

    If ``previous_chunks`` is provided, unchanged chunks (by content_hash)
    are skipped during embedding — their embeddings are reused from the
    existing vector store.
    """
    l3 = chunks.l3_chunks
    # Build set of unchanged content hashes for cache reuse
    unchanged_hashes: set[str] = set()
    if previous_chunks:
        old_hashes = {c.content_hash for c in previous_chunks.l3_chunks if c.content_hash}
        unchanged_hashes = {
            c.content_hash for c in l3 if c.content_hash and c.content_hash in old_hashes
        }
        if unchanged_hashes:
            logger.info(
                "Chunk cache: %d/%d chunks unchanged, will reuse embeddings",
                len(unchanged_hashes),
                len(l3),
            )

    if not l3:
        logger.warning("No L3 chunks to index")
        vector_store = VectorStore(doc_dir / "chroma")
        bm25_store = BM25Store()
        concept_index = ConceptIndex()
        return vector_store, bm25_store, concept_index

    # --- Collect all texts to embed ---
    embed_ids: list[str] = []
    embed_texts: list[str] = []
    embed_meta: list[dict] = []

    skipped = 0
    for chunk in l3:
        # Skip embedding for unchanged chunks (cache reuse)
        if chunk.content_hash and chunk.content_hash in unchanged_hashes:
            skipped += 1
            continue

        base_meta = {
            "chunk_id": chunk.chunk_id,
            "chapter": chunk.position.chapter,
            "section": chunk.position.section,
        }

        # 1) Content embedding (with context_prefix if present)
        content_text = chunk.content
        if chunk.context_prefix:
            content_text = chunk.context_prefix + "\n\n" + chunk.content
        embed_ids.append(f"{chunk.chunk_id}::content")
        embed_texts.append(content_text)
        embed_meta.append({**base_meta, "embedding_type": "content"})

        # 2) Summary embedding (if enriched)
        if chunk.summary:
            embed_ids.append(f"{chunk.chunk_id}::summary")
            embed_texts.append(chunk.summary)
            embed_meta.append({**base_meta, "embedding_type": "summary"})

        # 3) Hypothetical question embeddings (if enriched)
        for i, q in enumerate(chunk.hypothetical_questions):
            embed_ids.append(f"{chunk.chunk_id}::q{i}")
            embed_texts.append(q)
            embed_meta.append({**base_meta, "embedding_type": "question"})

    # 4) L0 digest embeddings (executive_summary + key_findings)
    l0 = chunks.l0
    l0_meta = {"chunk_id": l0.chunk_id, "chapter": "", "section": ""}
    if l0.executive_summary:
        embed_ids.append(f"{l0.chunk_id}::exec_summary")
        embed_texts.append(l0.executive_summary)
        embed_meta.append({**l0_meta, "embedding_type": "executive_summary"})

    for i, finding in enumerate(l0.key_findings):
        embed_ids.append(f"{l0.chunk_id}::finding{i}")
        embed_texts.append(finding)
        embed_meta.append({**l0_meta, "embedding_type": "key_finding"})

    if skipped:
        logger.info("Skipped %d unchanged chunks (cache hit)", skipped)
    logger.info("Generating %d embeddings...", len(embed_texts))
    embeddings = embedder.embed_passages(embed_texts)

    # --- Vector store ---
    vector_store = VectorStore(doc_dir / "chroma")
    vector_store.add_embeddings(
        ids=embed_ids,
        embeddings=embeddings,
        metadatas=embed_meta,
        documents=embed_texts,
    )
    logger.info("Vector store: %d embeddings indexed", vector_store.count)

    # --- BM25 ---
    bm25_store = BM25Store(language=language)
    bm25_ids = [c.chunk_id for c in l3]
    bm25_texts = []
    for c in l3:
        parts = [c.content]
        if c.keywords:
            parts.append(" ".join(c.keywords))
        bm25_texts.append(" ".join(parts))

    bm25_store.add_documents(bm25_ids, bm25_texts)
    bm25_store.build()
    bm25_store.save(doc_dir / "bm25_index.pkl")
    logger.info("BM25 store: %d documents indexed", bm25_store.count)

    # --- Concept index ---
    concept_index = ConceptIndex()
    for c in l3:
        concept_index.add_many(c.concepts, c.chunk_id)
        concept_index.add_many(c.keywords, c.chunk_id)
    concept_index.save(doc_dir / "concept_index.json")
    logger.info("Concept index: %d concepts indexed", concept_index.count)

    return vector_store, bm25_store, concept_index
