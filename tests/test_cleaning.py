"""Tests for Stage 1b — Preprocessing/Cleaning."""

from __future__ import annotations

from ingestible.models.document import PageContent, ParsedDocument
from ingestible.pipeline.stage1b_clean import (
    _collapse_whitespace,
    _detect_repeated_lines,
    _filter_empty_sections,
    _normalize_unicode,
    clean_document,
)


def _make_doc(pages_md: list[str], fmt: str = "pdf") -> ParsedDocument:
    pages = [PageContent(page_num=i + 1, markdown=md) for i, md in enumerate(pages_md)]
    return ParsedDocument(
        title="Test",
        source_path="/test.pdf",
        source_format=fmt,
        total_pages=len(pages),
        pages=pages,
    )


def test_normalize_unicode():
    # NFC combines decomposed characters
    decomposed = "e\u0301"  # é as e + combining acute
    assert _normalize_unicode(decomposed) == "\u00e9"  # é as single codepoint


def test_collapse_whitespace():
    text = "hello   world\t\there\r\nline2\n\n\n\nextra"
    result = _collapse_whitespace(text)
    assert "   " not in result
    assert "\t" not in result
    assert "\r\n" not in result
    assert "\n\n\n" not in result
    assert "hello world here" in result


def test_header_footer_detection_multi_page():
    """Repeated first/last lines across >50% of pages are detected."""
    pages = [
        PageContent(page_num=i, markdown=f"HEADER LINE\nContent for page {i} " * 20 + "\nPage {i}")
        for i in range(1, 7)
    ]
    headers, footers = _detect_repeated_lines(pages, threshold=0.5)
    assert "HEADER LINE" in headers


def test_header_footer_single_page_skip():
    """Single-page documents shouldn't attempt header/footer detection."""
    doc = _make_doc(["HEADER\nSome content here.\nFOOTER"])
    result = clean_document(doc)
    # Should pass through without error — single page, <3 eligible
    assert result.pages[0].markdown.strip()


def test_short_pages_skipped():
    """Pages with <50 chars are skipped for header/footer detection."""
    pages = [PageContent(page_num=1, markdown="Hi")]
    headers, footers = _detect_repeated_lines(pages, threshold=0.5)
    assert headers == set()
    assert footers == set()


def test_filter_empty_sections():
    text = "## Empty Section\n\n## Next Section\n\nSome content here."
    result = _filter_empty_sections(text)
    assert "Empty Section" not in result
    assert "Next Section" in result
    assert "Some content here" in result


def test_filter_empty_sections_at_end():
    text = "## Real Section\n\nContent.\n\n## Trailing Empty"
    result = _filter_empty_sections(text)
    assert "Real Section" in result
    assert "Content." in result
    assert "Trailing Empty" not in result


def test_non_pdf_skip_headers():
    """Non-PDF docs should skip header/footer removal but still clean text."""
    doc = _make_doc(
        ["Header\nContent " * 30 + "\nFooter"] * 5,
        fmt="markdown",
    )
    result = clean_document(doc)
    # Pages still cleaned (whitespace etc.) but headers not stripped
    assert len(result.pages) == 5


def test_full_clean_pipeline():
    """End-to-end: NFC + whitespace + empty section removal."""
    doc = _make_doc(["e\u0301  hello   world\t\there\n\n## Empty\n\n## Real\n\nStuff"])
    result = clean_document(doc)
    md = result.pages[0].markdown
    assert "\u00e9" in md  # NFC
    assert "   " not in md  # collapsed
    assert "Empty" not in md  # removed
    assert "Stuff" in md
