"""Tests for WP 5.3 — Chunk-Level Cache Invalidation."""

from __future__ import annotations

from ingestible.models.chunks import ChunkPosition, ChunkSet, L0Chunk, L3Chunk


def test_l3_chunk_content_hash_field():
    """L3Chunk has a content_hash field defaulting to empty string."""
    chunk = L3Chunk(
        chunk_id="p0",
        content="Hello world",
        position=ChunkPosition(chapter="ch1", section="sec1", index=0),
    )
    assert chunk.content_hash == ""


def test_l3_chunk_content_hash_set():
    chunk = L3Chunk(
        chunk_id="p0",
        content="Hello world",
        position=ChunkPosition(chapter="ch1", section="sec1", index=0),
        content_hash="abc123",
    )
    assert chunk.content_hash == "abc123"


def test_content_hash_survives_model_dump():
    chunk = L3Chunk(
        chunk_id="p0",
        content="Test",
        position=ChunkPosition(chapter="ch1", section="sec1", index=0),
        content_hash="deadbeef",
    )
    data = chunk.model_dump()
    assert data["content_hash"] == "deadbeef"

    restored = L3Chunk(**data)
    assert restored.content_hash == "deadbeef"


def test_unchanged_hashes_detection():
    """Simulate the cache logic from build_indexes."""
    old_chunks = [
        L3Chunk(
            chunk_id="p0", content="Same content",
            position=ChunkPosition(chapter="ch1", section="s1", index=0),
            content_hash="hash_a",
        ),
        L3Chunk(
            chunk_id="p1", content="Old content",
            position=ChunkPosition(chapter="ch1", section="s1", index=1),
            content_hash="hash_b",
        ),
    ]
    new_chunks = [
        L3Chunk(
            chunk_id="p0", content="Same content",
            position=ChunkPosition(chapter="ch1", section="s1", index=0),
            content_hash="hash_a",
        ),
        L3Chunk(
            chunk_id="p1", content="New content",
            position=ChunkPosition(chapter="ch1", section="s1", index=1),
            content_hash="hash_c",
        ),
    ]

    old_hashes = {c.content_hash for c in old_chunks if c.content_hash}
    unchanged = {c.content_hash for c in new_chunks if c.content_hash and c.content_hash in old_hashes}

    assert unchanged == {"hash_a"}
    assert "hash_c" not in unchanged
