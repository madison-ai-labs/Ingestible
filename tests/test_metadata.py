"""Tests for WP 1.3 — Document metadata extraction."""

from __future__ import annotations

from pathlib import Path

from ingestible.models.metadata import DocumentMetadata
from ingestible.pipeline.metadata import extract_metadata, _parse_pdf_date


def test_metadata_model_defaults():
    """DocumentMetadata has sensible defaults."""
    m = DocumentMetadata()
    assert m.author == ""
    assert m.keywords == []
    assert m.word_count == 0


def test_metadata_model_fields():
    """DocumentMetadata accepts all expected fields."""
    m = DocumentMetadata(
        author="Alice",
        creator="LibreOffice",
        subject="Testing",
        keywords=["test", "example"],
        creation_date="2024-01-15",
        language="en",
        page_count=10,
        word_count=5000,
    )
    assert m.author == "Alice"
    assert m.keywords == ["test", "example"]
    assert m.page_count == 10


def test_parse_pdf_date_full():
    """PDF date with full datetime parses correctly."""
    assert _parse_pdf_date("D:20240115103045") == "2024-01-15T10:30:45"


def test_parse_pdf_date_date_only():
    """PDF date with date only parses to date."""
    assert _parse_pdf_date("D:20240115") == "2024-01-15"


def test_parse_pdf_date_empty():
    """Empty string returns empty."""
    assert _parse_pdf_date("") == ""


def test_extract_text_metadata(tmp_path: Path):
    """Text file metadata extracts word count."""
    f = tmp_path / "test.txt"
    f.write_text("Hello world this is a test document")
    m = extract_metadata(f)
    assert m.word_count == 7


def test_extract_markdown_metadata(tmp_path: Path):
    """Markdown file uses text extractor."""
    f = tmp_path / "test.md"
    f.write_text("# Title\n\nSome content here with several words in it")
    m = extract_metadata(f)
    assert m.word_count > 0


def test_extract_html_metadata(tmp_path: Path):
    """HTML metadata extracts from meta tags."""
    f = tmp_path / "test.html"
    f.write_text(
        '<html lang="en">'
        '<head><meta name="author" content="Bob Smith">'
        '<meta name="keywords" content="python, testing"></head>'
        "<body><p>Hello world</p></body></html>"
    )
    m = extract_metadata(f)
    assert m.author == "Bob Smith"
    assert "python" in m.keywords
    assert "testing" in m.keywords
    assert m.language == "en"


def test_extract_html_no_meta(tmp_path: Path):
    """HTML without meta tags still works."""
    f = tmp_path / "test.html"
    f.write_text("<html><body>Hello</body></html>")
    m = extract_metadata(f)
    assert m.author == ""
    assert m.word_count > 0


def test_extract_unsupported_returns_empty(tmp_path: Path):
    """Unsupported format returns empty metadata gracefully."""
    f = tmp_path / "test.xyz"
    f.write_text("data")
    m = extract_metadata(f)
    assert isinstance(m, DocumentMetadata)


def test_l0_chunk_has_new_fields():
    """L0Chunk has creation_date and source_language fields."""
    from ingestible.models.chunks import L0Chunk

    l0 = L0Chunk(
        chunk_id="test",
        title="Test",
        creation_date="2024-01-01",
        source_language="en",
    )
    assert l0.creation_date == "2024-01-01"
    assert l0.source_language == "en"


def test_parsed_document_has_metadata_field():
    """ParsedDocument accepts optional metadata."""
    from ingestible.models.document import ParsedDocument

    m = DocumentMetadata(author="Alice")
    doc = ParsedDocument(
        title="Test",
        source_path="/tmp/test.pdf",
        metadata=m,
    )
    assert doc.metadata is not None
    assert doc.metadata.author == "Alice"


def test_parsed_document_metadata_none_by_default():
    """ParsedDocument metadata defaults to None."""
    from ingestible.models.document import ParsedDocument

    doc = ParsedDocument(title="Test", source_path="/tmp/test.pdf")
    assert doc.metadata is None
