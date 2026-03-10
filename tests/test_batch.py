"""Tests for batch/directory ingestion (WP 1.2)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ingestion_tool.pipeline.batch import (
    BatchReport,
    FileResult,
    discover_files,
    ingest_batch,
)


# ---------------------------------------------------------------------------
# discover_files
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_dir(tmp_path: Path) -> Path:
    """Create a directory with mixed file types."""
    (tmp_path / "doc1.pdf").write_bytes(b"%PDF-1.4 fake")
    (tmp_path / "doc2.md").write_text("# Hello")
    (tmp_path / "notes.txt").write_text("plain text")
    (tmp_path / "data.csv").write_text("a,b\n1,2")  # unsupported
    (tmp_path / "image.png").write_bytes(b"\x89PNG fake")  # unsupported
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "deep.docx").write_bytes(b"PK fake docx")
    (tmp_path / "sub" / "page.html").write_text("<h1>hi</h1>")
    return tmp_path


def test_discover_directory_recursive(sample_dir: Path):
    files = discover_files(sample_dir, recursive=True)
    names = {f.name for f in files}
    assert names == {"doc1.pdf", "doc2.md", "notes.txt", "deep.docx", "page.html"}


def test_discover_directory_non_recursive(sample_dir: Path):
    files = discover_files(sample_dir, recursive=False)
    names = {f.name for f in files}
    assert names == {"doc1.pdf", "doc2.md", "notes.txt"}


def test_discover_single_supported_file(tmp_path: Path):
    f = tmp_path / "test.md"
    f.write_text("# Test")
    assert discover_files(f) == [f]


def test_discover_single_unsupported_file(tmp_path: Path):
    f = tmp_path / "test.csv"
    f.write_text("a,b")
    assert discover_files(f) == []


def test_discover_glob_pattern(sample_dir: Path):
    pattern = str(sample_dir / "*.md")
    files = discover_files(pattern)
    assert len(files) == 1
    assert files[0].name == "doc2.md"


def test_discover_empty_directory(tmp_path: Path):
    assert discover_files(tmp_path) == []


def test_discover_nonexistent_path():
    assert discover_files("/nonexistent/path") == []


# ---------------------------------------------------------------------------
# ingest_batch
# ---------------------------------------------------------------------------


@patch("ingestion_tool.pipeline.orchestrator.ingest")
@patch("ingestion_tool.pipeline.orchestrator.generate_doc_id")
def test_ingest_batch_sequential(mock_gen_id, mock_ingest, sample_dir: Path):
    """Batch ingestion processes all supported files and reports results."""
    mock_gen_id.side_effect = lambda p: f"id-{p.stem}"
    mock_ingest.side_effect = lambda fp, settings, **kw: Path(f"/data/{fp.stem}")

    settings = MagicMock()
    report = ingest_batch(sample_dir, settings, skip_enrichment=True, parallel=1)

    assert isinstance(report, BatchReport)
    assert report.total == 5  # pdf, md, txt, docx, html
    assert report.succeeded == 5
    assert report.failed == 0
    assert len(report.results) == 5


@patch("ingestion_tool.pipeline.orchestrator.ingest")
@patch("ingestion_tool.pipeline.orchestrator.generate_doc_id")
def test_ingest_batch_error_isolation(mock_gen_id, mock_ingest, sample_dir: Path):
    """One file failing doesn't abort the batch."""

    def side_effect(fp, settings, **kw):
        if fp.suffix == ".pdf":
            raise RuntimeError("PDF parse error")
        return Path(f"/data/{fp.stem}")

    mock_gen_id.side_effect = lambda p: f"id-{p.stem}"
    mock_ingest.side_effect = side_effect

    settings = MagicMock()
    report = ingest_batch(sample_dir, settings, parallel=1)

    assert report.total == 5
    assert report.failed == 1
    assert report.succeeded == 4

    failed = [r for r in report.results if r.error]
    assert len(failed) == 1
    assert "PDF parse error" in failed[0].error


@patch("ingestion_tool.pipeline.orchestrator.ingest")
@patch("ingestion_tool.pipeline.orchestrator.generate_doc_id")
def test_ingest_batch_empty_dir(mock_gen_id, mock_ingest, tmp_path: Path):
    """Empty directory produces empty report."""
    settings = MagicMock()
    report = ingest_batch(tmp_path, settings)

    assert report.total == 0
    assert report.succeeded == 0
    assert report.failed == 0
    mock_ingest.assert_not_called()
