"""Pluggable vector store abstraction.

Provides a VectorBackend ABC and concrete implementations for ChromaDB,
pgvector, and Qdrant. The factory function ``create_vector_backend`` selects
the right backend based on configuration.
"""

from __future__ import annotations

import hashlib
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Abstract base class
# ---------------------------------------------------------------------------


class VectorBackend(ABC):
    """Abstract vector store interface."""

    @abstractmethod
    def add_embeddings(
        self,
        ids: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict],
        documents: list[str],
    ) -> None:
        """Add embeddings to the store."""

    @abstractmethod
    def query(
        self,
        embedding: list[float],
        n_results: int = 10,
    ) -> list[tuple[str, float, dict]]:
        """Query nearest neighbours. Returns ``(id, distance, metadata)`` tuples."""

    @property
    @abstractmethod
    def count(self) -> int:
        """Number of embeddings in the store."""

    @abstractmethod
    def delete_all(self) -> None:
        """Remove all embeddings."""


# ---------------------------------------------------------------------------
# ChromaDB adapter
# ---------------------------------------------------------------------------


class ChromaBackend(VectorBackend):
    """ChromaDB vector backend (default). Wraps the existing VectorStore."""

    def __init__(self, path: Path) -> None:
        from ingestible.search.vector_store import VectorStore

        self._store = VectorStore(path)

    def add_embeddings(
        self,
        ids: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict],
        documents: list[str],
    ) -> None:
        self._store.add_embeddings(ids, embeddings, metadatas, documents)

    def query(
        self,
        embedding: list[float],
        n_results: int = 10,
    ) -> list[tuple[str, float, dict]]:
        return self._store.query(embedding, n_results=n_results)

    @property
    def count(self) -> int:
        return self._store.count

    def delete_all(self) -> None:
        self._store._collection.delete(where={"chunk_id": {"$ne": ""}})
        # Fall back to ID-based delete when the where-clause is unsupported or
        # the collection uses no metadata.  ChromaDB's ``get()`` returns all
        # IDs which we can then pass to ``delete()``.
        if self._store.count > 0:
            all_ids = self._store._collection.get()["ids"]
            if all_ids:
                self._store._collection.delete(ids=all_ids)


# ---------------------------------------------------------------------------
# Pgvector backend
# ---------------------------------------------------------------------------

_PGVECTOR_TABLE_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


class PgvectorBackend(VectorBackend):
    """PostgreSQL pgvector backend for production deployments.

    Requires::

        pip install "psycopg[binary]" pgvector

    Connection string via *connection_url* (or ``INGEST_PGVECTOR_URL``).
    A table is auto-created per document (the *table_name* argument is
    sanitised to a valid SQL identifier).
    """

    def __init__(
        self,
        connection_url: str,
        table_name: str,
        dimensions: int = 1024,
    ) -> None:
        try:
            import psycopg  # noqa: F401
            from pgvector.psycopg import register_vector  # noqa: F401
        except ImportError:
            raise ImportError(
                "pgvector backend requires psycopg and pgvector. "
                'Install with: pip install "psycopg[binary]" pgvector'
            )

        safe_name = re.sub(r"[^a-zA-Z0-9_]", "_", table_name)
        if not _PGVECTOR_TABLE_RE.match(safe_name):
            safe_name = f"vec_{safe_name}"
        self._table = safe_name
        self._dims = dimensions
        self._url = connection_url
        self._conn: psycopg.Connection | None = None
        self._setup_done = False

    # -- lazy connection & schema bootstrap -----------------------------------

    def _get_conn(self):
        import psycopg
        from pgvector.psycopg import register_vector

        if self._conn is None or self._conn.closed:
            try:
                self._conn = psycopg.connect(self._url, autocommit=True)
                register_vector(self._conn)
            except psycopg.OperationalError as exc:
                raise ConnectionError(
                    f"Could not connect to PostgreSQL at {self._url!r}: {exc}"
                ) from exc
        if not self._setup_done:
            with self._conn.cursor() as cur:
                cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
                cur.execute(
                    f"CREATE TABLE IF NOT EXISTS {self._table} ("
                    f"  id TEXT PRIMARY KEY,"
                    f"  embedding vector({self._dims}),"
                    f"  metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,"
                    f"  document TEXT NOT NULL DEFAULT ''"
                    f")"
                )
                cur.execute(
                    f"CREATE INDEX IF NOT EXISTS {self._table}_ivfflat_idx "
                    f"ON {self._table} USING ivfflat (embedding vector_cosine_ops)"
                )
            self._setup_done = True
        return self._conn

    # -- VectorBackend interface ----------------------------------------------

    def add_embeddings(
        self,
        ids: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict],
        documents: list[str],
    ) -> None:
        import json

        conn = self._get_conn()
        with conn.cursor() as cur:
            for eid, emb, meta, doc in zip(ids, embeddings, metadatas, documents):
                cur.execute(
                    f"INSERT INTO {self._table} (id, embedding, metadata, document) "
                    f"VALUES (%s, %s::vector, %s::jsonb, %s) "
                    f"ON CONFLICT (id) DO UPDATE SET "
                    f"  embedding = EXCLUDED.embedding,"
                    f"  metadata = EXCLUDED.metadata,"
                    f"  document = EXCLUDED.document",
                    (eid, str(emb), json.dumps(meta), doc),
                )

    def query(
        self,
        embedding: list[float],
        n_results: int = 10,
    ) -> list[tuple[str, float, dict]]:
        import json

        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT id, embedding <=> %s::vector AS distance, metadata "
                f"FROM {self._table} "
                f"ORDER BY distance LIMIT %s",
                (str(embedding), n_results),
            )
            rows = cur.fetchall()

        results: list[tuple[str, float, dict]] = []
        for row_id, dist, meta in rows:
            if isinstance(meta, str):
                meta = json.loads(meta)
            results.append((row_id, float(dist), meta))
        return results

    @property
    def count(self) -> int:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM {self._table}")
            row = cur.fetchone()
            return row[0] if row else 0

    def delete_all(self) -> None:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(f"DELETE FROM {self._table}")


# ---------------------------------------------------------------------------
# Qdrant backend
# ---------------------------------------------------------------------------


class QdrantBackend(VectorBackend):
    """Qdrant vector backend.

    Requires::

        pip install qdrant-client

    Connection via *url* (or ``INGEST_QDRANT_URL``, default ``http://localhost:6333``).
    One collection per document.
    """

    def __init__(
        self,
        url: str,
        collection_name: str,
        dimensions: int = 1024,
    ) -> None:
        try:
            from qdrant_client import QdrantClient  # noqa: F401
            from qdrant_client.models import Distance, VectorParams  # noqa: F401
        except ImportError:
            raise ImportError(
                "Qdrant backend requires qdrant-client. Install with: pip install qdrant-client"
            )

        self._collection = collection_name
        self._dims = dimensions

        try:
            self._client = QdrantClient(url=url)
        except Exception as exc:
            raise ConnectionError(f"Could not connect to Qdrant at {url!r}: {exc}") from exc

        self._ensure_collection()

    def _ensure_collection(self) -> None:
        from qdrant_client.models import Distance, VectorParams

        collections = [c.name for c in self._client.get_collections().collections]
        if self._collection not in collections:
            self._client.create_collection(
                collection_name=self._collection,
                vectors_config=VectorParams(
                    size=self._dims,
                    distance=Distance.COSINE,
                ),
            )

    # -- VectorBackend interface ----------------------------------------------

    def add_embeddings(
        self,
        ids: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict],
        documents: list[str],
    ) -> None:
        from qdrant_client.models import PointStruct

        def _str_to_int_id(s: str) -> int:
            """Deterministic string-to-int mapping for Qdrant point IDs."""
            return int(hashlib.md5(s.encode(), usedforsecurity=False).hexdigest()[:16], 16)

        points = [
            PointStruct(
                id=_str_to_int_id(eid),
                vector=emb,
                payload={**meta, "_document": doc, "_str_id": eid},
            )
            for eid, emb, meta, doc in zip(ids, embeddings, metadatas, documents)
        ]
        self._client.upsert(collection_name=self._collection, points=points)

    def query(
        self,
        embedding: list[float],
        n_results: int = 10,
    ) -> list[tuple[str, float, dict]]:
        hits = self._client.search(
            collection_name=self._collection,
            query_vector=embedding,
            limit=n_results,
        )
        results: list[tuple[str, float, dict]] = []
        for hit in hits:
            payload = dict(hit.payload) if hit.payload else {}
            str_id = payload.pop("_str_id", str(hit.id))
            payload.pop("_document", None)
            # Qdrant returns similarity score; convert to distance for consistency
            distance = 1.0 - hit.score
            results.append((str_id, distance, payload))
        return results

    @property
    def count(self) -> int:
        info = self._client.get_collection(self._collection)
        return info.points_count or 0

    def delete_all(self) -> None:
        from qdrant_client.models import Distance, VectorParams

        self._client.delete_collection(self._collection)
        self._client.create_collection(
            collection_name=self._collection,
            vectors_config=VectorParams(
                size=self._dims,
                distance=Distance.COSINE,
            ),
        )


# ---------------------------------------------------------------------------
# Configuration dataclass
# ---------------------------------------------------------------------------


@dataclass
class VectorBackendConfig:
    """Configuration for the vector backend."""

    backend: str = "chroma"  # "chroma", "pgvector", "qdrant"
    pgvector_url: str = ""
    qdrant_url: str = "http://localhost:6333"
    dimensions: int = 1024


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

_BACKENDS = {"chroma", "pgvector", "qdrant"}


def create_vector_backend(
    backend_type: str,
    *,
    path: Path | None = None,
    connection_url: str | None = None,
    collection_name: str = "default",
    dimensions: int = 1024,
) -> VectorBackend:
    """Create a vector backend instance.

    Parameters
    ----------
    backend_type:
        One of ``"chroma"``, ``"pgvector"``, ``"qdrant"``.
    path:
        Filesystem path for ChromaDB persistence (required for ``"chroma"``).
    connection_url:
        Database/service URL (required for ``"pgvector"`` and ``"qdrant"``).
    collection_name:
        Collection or table name used by the backend.
    dimensions:
        Embedding dimensionality (used by pgvector and qdrant).

    Returns
    -------
    VectorBackend
    """
    backend_type = backend_type.lower()
    if backend_type not in _BACKENDS:
        raise ValueError(
            f"Unknown vector backend {backend_type!r}. "
            f"Supported backends: {', '.join(sorted(_BACKENDS))}"
        )

    if backend_type == "chroma":
        if path is None:
            raise ValueError("ChromaBackend requires a 'path' argument.")
        return ChromaBackend(path)

    if backend_type == "pgvector":
        if not connection_url:
            raise ValueError(
                "PgvectorBackend requires a 'connection_url' argument (e.g. INGEST_PGVECTOR_URL)."
            )
        return PgvectorBackend(connection_url, collection_name, dimensions)

    # qdrant
    url = connection_url or "http://localhost:6333"
    return QdrantBackend(url, collection_name, dimensions)
