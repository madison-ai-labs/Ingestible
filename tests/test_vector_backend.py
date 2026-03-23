"""Tests for the pluggable vector backend abstraction."""

from __future__ import annotations

import builtins
from unittest.mock import patch

import pytest

from ingestible.search.vector_backend import (
    ChromaBackend,
    VectorBackend,
    create_vector_backend,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_embedding(dim: int = 384, val: float = 0.1) -> list[float]:
    return [val] * dim


# ---------------------------------------------------------------------------
# ABC contract
# ---------------------------------------------------------------------------


def test_abc_cannot_be_instantiated():
    """VectorBackend is abstract and must not be instantiated directly."""
    with pytest.raises(TypeError):
        VectorBackend()  # type: ignore[abstract]


# ---------------------------------------------------------------------------
# ChromaBackend integration (uses real ChromaDB with tmp_path)
# ---------------------------------------------------------------------------


def test_chroma_add_and_query(tmp_path):
    backend = ChromaBackend(tmp_path / "chroma")
    emb = _make_embedding()

    backend.add_embeddings(
        ids=["a", "b"],
        embeddings=[_make_embedding(val=0.1), _make_embedding(val=0.9)],
        metadatas=[{"chunk_id": "a"}, {"chunk_id": "b"}],
        documents=["hello world", "goodbye world"],
    )

    results = backend.query(emb, n_results=5)
    assert len(results) > 0
    # Each result is (id, distance, metadata)
    for rid, dist, meta in results:
        assert isinstance(rid, str)
        assert isinstance(dist, float)
        assert isinstance(meta, dict)


def test_chroma_count(tmp_path):
    backend = ChromaBackend(tmp_path / "chroma")
    assert backend.count == 0

    backend.add_embeddings(
        ids=["x"],
        embeddings=[_make_embedding()],
        metadatas=[{"chunk_id": "x"}],
        documents=["doc"],
    )
    assert backend.count == 1


def test_chroma_delete_all(tmp_path):
    backend = ChromaBackend(tmp_path / "chroma")
    backend.add_embeddings(
        ids=["a", "b", "c"],
        embeddings=[_make_embedding(val=v) for v in (0.1, 0.5, 0.9)],
        metadatas=[{"chunk_id": i} for i in ("a", "b", "c")],
        documents=["d1", "d2", "d3"],
    )
    assert backend.count == 3

    backend.delete_all()
    assert backend.count == 0


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def test_factory_chroma(tmp_path):
    backend = create_vector_backend("chroma", path=tmp_path / "chroma")
    assert isinstance(backend, ChromaBackend)


def test_factory_unknown_raises():
    with pytest.raises(ValueError, match="Unknown vector backend"):
        create_vector_backend("redis")


def test_factory_chroma_requires_path():
    with pytest.raises(ValueError, match="requires a 'path'"):
        create_vector_backend("chroma")


def test_factory_pgvector_requires_url():
    with pytest.raises((ValueError, ImportError)):
        create_vector_backend("pgvector")


# ---------------------------------------------------------------------------
# Import-error paths for optional backends
# ---------------------------------------------------------------------------


def _block_import(*blocked_modules):
    """Return a side_effect function for builtins.__import__ that blocks certain modules."""
    real_import = builtins.__import__

    def _import(name, *args, **kwargs):
        for mod in blocked_modules:
            if name == mod or name.startswith(mod + "."):
                raise ImportError(f"Mocked: no module named {name!r}")
        return real_import(name, *args, **kwargs)

    return _import


def test_pgvector_import_error():
    """PgvectorBackend raises ImportError with install instructions when psycopg missing."""
    from ingestible.search.vector_backend import PgvectorBackend

    with patch("builtins.__import__", side_effect=_block_import("psycopg", "pgvector")):
        with pytest.raises(ImportError, match="psycopg"):
            PgvectorBackend("postgresql://localhost/test", "tbl")


def test_qdrant_import_error():
    """QdrantBackend raises ImportError with install instructions when qdrant_client missing."""
    from ingestible.search.vector_backend import QdrantBackend

    with patch("builtins.__import__", side_effect=_block_import("qdrant_client")):
        with pytest.raises(ImportError, match="qdrant-client"):
            QdrantBackend("http://localhost:6333", "col")
