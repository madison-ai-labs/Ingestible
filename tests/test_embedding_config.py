"""Tests for WP 4.1 — Configurable embedding dimensions / quantization."""

from __future__ import annotations

import math

from ingestible.config import Settings
from ingestible.pipeline.stage5_embedding import Embedder


def test_settings_embedding_dimensions_default():
    s = Settings()
    assert s.embedding_dimensions is None
    assert s.embedding_quantization == "none"


def test_settings_embedding_dimensions_custom():
    s = Settings(embedding_dimensions=256, embedding_quantization="binary")
    assert s.embedding_dimensions == 256
    assert s.embedding_quantization == "binary"


def test_post_process_no_truncation():
    """Without truncation, vector is unchanged."""
    s = Settings()
    e = Embedder(s)
    vec = [0.1, 0.2, 0.3, 0.4]
    result = e._post_process(vec)
    assert result == vec


def test_post_process_truncation():
    """Matryoshka truncation reduces dimension count."""
    s = Settings(embedding_dimensions=2)
    e = Embedder(s)
    vec = [0.6, 0.8, 0.0, 0.0]  # already normalized
    result = e._post_process(vec)
    assert len(result) == 2
    # Should be re-normalized
    norm = math.sqrt(sum(x * x for x in result))
    assert abs(norm - 1.0) < 0.01


def test_post_process_binary_quantization():
    """Binary quantization maps to 0/1."""
    s = Settings(embedding_quantization="binary")
    e = Embedder(s)
    vec = [0.5, -0.3, 0.1, -0.9, 0.0]
    result = e._post_process(vec)
    assert result == [1.0, 0.0, 1.0, 0.0, 1.0]  # >= 0 -> 1, < 0 -> 0


def test_post_process_truncation_then_binary():
    """Truncation + binary quantization applied in order."""
    s = Settings(embedding_dimensions=3, embedding_quantization="binary")
    e = Embedder(s)
    vec = [0.5, -0.3, 0.1, -0.9, 0.0]
    result = e._post_process(vec)
    assert len(result) == 3
    # After truncation and normalization, all values are non-negative or mixed
    # but after binary quantization, should be 0 or 1
    assert all(v in (0.0, 1.0) for v in result)
