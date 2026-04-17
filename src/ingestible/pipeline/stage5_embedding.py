"""Stage 5 — Embedding & Indexing.

Supports local models via sentence-transformers and API providers
(OpenAI, Cohere, Voyage). Default: BAAI/bge-en-icl (local).
Builds: ChromaDB vector index, BM25 sparse index, concept index.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ingestible.config import Settings
from ingestible.models.chunks import ChunkSet
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
    """Manages embedding generation. Supports local (sentence-transformers) and
    API providers (OpenAI, Cohere, Voyage)."""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._model: Any = None
        self._provider = settings.embedding_provider

    @property
    def model(self):
        """Lazy-load the local sentence-transformers model."""
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            logger.info("Loading embedding model: %s", self._settings.embedding_model)
            device = _resolve_device(self._settings.embedding_device)
            logger.info("Embedding device: %s", device)
            self._model = SentenceTransformer(
                self._settings.embedding_model,
                device=device,
            )
        return self._model

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        if self._provider == "openai":
            return self._embed_openai(texts)
        elif self._provider == "cohere":
            return self._embed_cohere(texts, input_type="search_document")
        elif self._provider == "voyage":
            return self._embed_voyage(texts, input_type="document")
        else:
            prefixed = [f"passage: {t}" for t in texts]
            embeddings = self.model.encode(
                prefixed, normalize_embeddings=True, show_progress_bar=True
            )
            result = embeddings.tolist()
            return [self._post_process(v) for v in result]

    def embed_query(self, query: str) -> list[float]:
        if self._provider == "openai":
            return self._embed_openai([query])[0]
        elif self._provider == "cohere":
            return self._embed_cohere([query], input_type="search_query")[0]
        elif self._provider == "voyage":
            return self._embed_voyage([query], input_type="query")[0]
        else:
            embedding = self.model.encode(f"query: {query}", normalize_embeddings=True)
            return self._post_process(embedding.tolist())

    def _embed_openai(self, texts: list[str]) -> list[list[float]]:
        """Embed via OpenAI API."""
        import openai

        api_key = self._settings.openai_embedding_api_key or self._settings.openai_api_key
        if not api_key:
            raise ValueError(
                "OpenAI embedding requires INGEST_OPENAI_EMBEDDING_API_KEY or INGEST_OPENAI_API_KEY"
            )
        client = openai.OpenAI(api_key=api_key)
        kwargs: dict[str, Any] = {"model": self._settings.embedding_model, "input": texts}
        if self._settings.embedding_dimensions:
            kwargs["dimensions"] = self._settings.embedding_dimensions
        response = client.embeddings.create(**kwargs)
        vectors = [
            item.embedding
            for item in sorted(response.data, key=lambda x: x.index if x.index is not None else 0)
        ]
        return [self._post_process(v) for v in vectors]

    def _embed_cohere(
        self, texts: list[str], input_type: str = "search_document"
    ) -> list[list[float]]:
        """Embed via Cohere API."""
        try:
            import cohere
        except ImportError:
            raise ImportError(
                "Cohere embedding requires the cohere package. Install with: pip install cohere"
            )
        if not self._settings.cohere_api_key:
            raise ValueError("Cohere embedding requires INGEST_COHERE_API_KEY")
        client = cohere.Client(api_key=self._settings.cohere_api_key)
        response = client.embed(
            texts=texts,
            model=self._settings.embedding_model,
            input_type=input_type,
        )
        vectors = response.embeddings
        return [self._post_process(v) for v in vectors]

    def _embed_voyage(self, texts: list[str], input_type: str = "document") -> list[list[float]]:
        """Embed via Voyage API."""
        try:
            import voyageai
        except ImportError:
            raise ImportError(
                "Voyage embedding requires the voyageai package. Install with: pip install voyageai"
            )
        if not self._settings.voyage_api_key:
            raise ValueError("Voyage embedding requires INGEST_VOYAGE_API_KEY")
        client = voyageai.Client(api_key=self._settings.voyage_api_key)
        response = client.embed(
            texts=texts,
            model=self._settings.embedding_model,
            input_type=input_type,
        )
        return [self._post_process(v) for v in response.embeddings]

    def _post_process(self, vector: list[float]) -> list[float]:
        """Apply Matryoshka truncation and/or binary quantization."""
        dims = self._settings.embedding_dimensions
        if dims is not None and dims < len(vector):
            vector = vector[:dims]
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
    access_tags: list[str] | None = None,
) -> tuple[VectorStore, BM25Store, ConceptIndex]:
    """Build all search indexes for a document.

    If ``previous_chunks`` is provided, unchanged chunks (by content_hash)
    are skipped during embedding — their embeddings are reused from the
    existing vector store.
    """
    access_tags_str = ",".join(access_tags) if access_tags else ""

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
        _backend = getattr(embedder._settings, "vector_backend", "chroma")
        if _backend in ("pgvector", "qdrant"):
            from ingestible.search.vector_backend import create_vector_backend

            vector_store = create_vector_backend(
                _backend,
                connection_url=embedder._settings.pgvector_url
                if _backend == "pgvector"
                else embedder._settings.qdrant_url,
                collection_name=chunks.doc_id,
                dimensions=embedder._settings.embedding_dimensions or 1024,
            )
        else:
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
            "version_status": "current",
            "access_tags": access_tags_str,
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
    l0_meta = {"chunk_id": l0.chunk_id, "chapter": "", "section": "", "version_status": "current"}
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
    _backend = getattr(embedder._settings, "vector_backend", "chroma")
    if _backend in ("pgvector", "qdrant"):
        from ingestible.search.vector_backend import create_vector_backend

        vector_store = create_vector_backend(
            _backend,
            connection_url=embedder._settings.pgvector_url
            if _backend == "pgvector"
            else embedder._settings.qdrant_url,
            collection_name=chunks.doc_id,
            dimensions=embedder._settings.embedding_dimensions or 1024,
        )
    else:
        vector_store = VectorStore(doc_dir / "chroma")
    vector_store.add_embeddings(
        ids=embed_ids,
        embeddings=embeddings,
        metadatas=embed_meta,
        documents=embed_texts,
    )
    logger.info("Vector store: %d embeddings indexed", vector_store.count)

    # --- Version-aware search: add superseded chunks from previous version ---
    if previous_chunks:
        new_hashes = {c.content_hash for c in l3 if c.content_hash}
        superseded = [
            c
            for c in previous_chunks.l3_chunks
            if c.content_hash and c.content_hash not in new_hashes
        ]
        if superseded:
            logger.info("Adding %d superseded chunks to vector index", len(superseded))
            sup_ids: list[str] = []
            sup_texts: list[str] = []
            sup_meta: list[dict] = []
            for chunk in superseded:
                meta = {
                    "chunk_id": chunk.chunk_id,
                    "chapter": chunk.position.chapter,
                    "section": chunk.position.section,
                    "version_status": "superseded",
                    "embedding_type": "content",
                }
                sup_ids.append(f"{chunk.chunk_id}::content")
                sup_texts.append(chunk.content)
                sup_meta.append(meta)

            sup_embeddings = embedder.embed_passages(sup_texts)
            vector_store.add_embeddings(
                ids=sup_ids,
                embeddings=sup_embeddings,
                metadatas=sup_meta,
                documents=sup_texts,
            )
            logger.info("Vector store: added %d superseded embeddings", len(sup_ids))

            # Persist superseded chunk data for search result rendering
            import json

            sup_data = [
                {
                    "chunk_id": c.chunk_id,
                    "content": c.content,
                    "summary": c.summary,
                    "chapter": c.position.chapter,
                    "section": c.position.section,
                    "page_start": c.page_start,
                    "page_end": c.page_end,
                    "version_status": "superseded",
                }
                for c in superseded
            ]
            sup_path = doc_dir / "superseded.json"
            sup_path.write_text(json.dumps(sup_data, indent=2, default=str), encoding="utf-8")

    # --- Sparse retrieval (BM25 or SPLADE) ---
    if embedder._settings.sparse_retrieval == "splade":
        from ingestible.search.splade_store import SpladeStore

        splade_store = SpladeStore(model_name=embedder._settings.splade_model)
        splade_ids = [c.chunk_id for c in l3]
        splade_texts = []
        for c in l3:
            parts = [c.content]
            if c.keywords:
                parts.append(" ".join(c.keywords))
            splade_texts.append(" ".join(parts))
        splade_store.add_documents(splade_ids, splade_texts)
        splade_store.save(doc_dir / "splade_index.json")
        logger.info("SPLADE store: %d documents indexed", splade_store.count)
        bm25_store = BM25Store()  # empty placeholder
    else:
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

    # --- KG index (if triples exist) ---
    if chunks.knowledge_graph or any(c.kg_triples for c in l3):
        from ingestible.search.kg_retrieval import KGIndex

        kg_index = KGIndex.from_chunks(chunks)
        kg_index.compute_graph_metrics(embedder._settings)
        kg_index.save(doc_dir / "kg_index.json")
        logger.info("KG index: %d entities indexed", len(kg_index._entity_chunks))

    return vector_store, bm25_store, concept_index
