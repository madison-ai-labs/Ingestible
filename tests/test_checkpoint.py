"""Tests for WP 1.1 — Pipeline checkpoint/resume."""

from __future__ import annotations

from pathlib import Path

from ingestible.models.chunks import ChunkSet, L0Chunk, L3Chunk
from ingestible.models.document import PageContent, ParsedDocument
from ingestible.pipeline.checkpoint import (
    STAGE_ORDER,
    clear_checkpoints,
    get_latest_checkpoint,
    load_checkpoint,
    save_checkpoint,
)


def _make_parsed() -> ParsedDocument:
    return ParsedDocument(
        title="Test Doc",
        source_path="/tmp/test.pdf",
        source_format="pdf",
        total_pages=1,
        pages=[PageContent(page_num=1, markdown="Hello world")],
    )


def _make_chunks() -> ChunkSet:
    return ChunkSet(
        doc_id="test-doc",
        l0=L0Chunk(chunk_id="test-doc-L0", title="Test Doc", total_pages=1),
        l3_chunks=[
            L3Chunk(chunk_id="test-doc-c1", content="Hello world"),
        ],
    )


def test_save_load_roundtrip(tmp_path: Path):
    """Checkpoint save → load round-trips a Pydantic model."""
    parsed = _make_parsed()
    save_checkpoint(tmp_path, "parsed", parsed)

    loaded = load_checkpoint(tmp_path, "parsed")
    assert loaded is not None
    restored = ParsedDocument(**loaded)
    assert restored.title == "Test Doc"
    assert restored.pages[0].markdown == "Hello world"


def test_load_missing_returns_none(tmp_path: Path):
    """Loading a non-existent checkpoint returns None."""
    assert load_checkpoint(tmp_path, "parsed") is None


def test_load_corrupt_returns_none(tmp_path: Path):
    """Loading a corrupt checkpoint file returns None."""
    cp_dir = tmp_path / ".checkpoint"
    cp_dir.mkdir()
    (cp_dir / "parsed.json").write_text("NOT JSON", encoding="utf-8")
    assert load_checkpoint(tmp_path, "parsed") is None


def test_get_latest_checkpoint(tmp_path: Path):
    """get_latest_checkpoint returns the most advanced stage."""
    parsed = _make_parsed()
    save_checkpoint(tmp_path, "parsed", parsed)
    assert get_latest_checkpoint(tmp_path) == "parsed"

    chunks = _make_chunks()
    save_checkpoint(tmp_path, "validated", chunks)
    assert get_latest_checkpoint(tmp_path) == "validated"


def test_get_latest_checkpoint_empty(tmp_path: Path):
    """No checkpoints → returns None."""
    assert get_latest_checkpoint(tmp_path) is None


def test_clear_checkpoints(tmp_path: Path):
    """clear_checkpoints removes the .checkpoint directory."""
    parsed = _make_parsed()
    save_checkpoint(tmp_path, "parsed", parsed)
    assert (tmp_path / ".checkpoint" / "parsed.json").exists()

    clear_checkpoints(tmp_path)
    assert not (tmp_path / ".checkpoint").exists()


def test_clear_checkpoints_noop_when_missing(tmp_path: Path):
    """clear_checkpoints is a no-op when no checkpoints exist."""
    clear_checkpoints(tmp_path)  # Should not raise


def test_chunkset_roundtrip(tmp_path: Path):
    """ChunkSet survives checkpoint save/load."""
    chunks = _make_chunks()
    save_checkpoint(tmp_path, "validated", chunks)

    loaded = load_checkpoint(tmp_path, "validated")
    assert loaded is not None
    restored = ChunkSet(**loaded)
    assert restored.doc_id == "test-doc"
    assert len(restored.l3_chunks) == 1
    assert restored.l3_chunks[0].content == "Hello world"


def test_stage_order_is_correct():
    """STAGE_ORDER contains all expected stages in pipeline order."""
    assert "parsed" in STAGE_ORDER
    assert "validated" in STAGE_ORDER
    assert "enriched" in STAGE_ORDER
    assert STAGE_ORDER.index("parsed") < STAGE_ORDER.index("validated")
    assert STAGE_ORDER.index("validated") < STAGE_ORDER.index("enriched")
