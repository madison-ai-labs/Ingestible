"""Tests for Phase 3 — New format parsers (WP 3.1–3.4)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ingestible.pipeline.stage1_parsing import parse_document, SUPPORTED_FORMATS


# ---------------------------------------------------------------------------
# WP 3.2: CSV
# ---------------------------------------------------------------------------


def test_parse_csv(tmp_path: Path):
    f = tmp_path / "data.csv"
    f.write_text("Name,Age,City\nAlice,30,NYC\nBob,25,LA\n")
    doc = parse_document(f)

    assert doc.source_format == "csv"
    assert doc.total_pages >= 1
    assert "Alice" in doc.full_markdown
    assert "| Name |" in doc.full_markdown


def test_parse_csv_empty(tmp_path: Path):
    f = tmp_path / "empty.csv"
    f.write_text("")
    doc = parse_document(f)
    assert doc.pages == []


def test_parse_csv_large(tmp_path: Path):
    """Large CSV is split into multiple pages."""
    lines = ["col1,col2"]
    for i in range(120):
        lines.append(f"val{i},data{i}")
    f = tmp_path / "big.csv"
    f.write_text("\n".join(lines))
    doc = parse_document(f)
    assert doc.total_pages > 1


# ---------------------------------------------------------------------------
# WP 3.2: Excel
# ---------------------------------------------------------------------------


def test_parse_excel(tmp_path: Path):
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(["Name", "Score"])
    ws.append(["Alice", 95])
    ws.append(["Bob", 87])

    f = tmp_path / "test.xlsx"
    wb.save(str(f))

    doc = parse_document(f)
    assert doc.source_format == "xlsx"
    assert doc.total_pages >= 1
    assert "Alice" in doc.full_markdown
    assert "## Sheet1" in doc.full_markdown


def test_parse_excel_multiple_sheets(tmp_path: Path):
    from openpyxl import Workbook

    wb = Workbook()
    ws1 = wb.active
    ws1.title = "Sales"
    ws1.append(["Product", "Revenue"])
    ws1.append(["Widget", 1000])

    ws2 = wb.create_sheet("Costs")
    ws2.append(["Item", "Amount"])
    ws2.append(["Rent", 500])

    f = tmp_path / "multi.xlsx"
    wb.save(str(f))

    doc = parse_document(f)
    assert doc.total_pages == 2
    assert "Sales" in doc.full_markdown
    assert "Costs" in doc.full_markdown


# ---------------------------------------------------------------------------
# WP 3.3: PowerPoint
# ---------------------------------------------------------------------------


def test_parse_pptx(tmp_path: Path):
    from pptx import Presentation
    from pptx.util import Inches

    prs = Presentation()
    slide_layout = prs.slide_layouts[1]  # title + content
    slide = prs.slides.add_slide(slide_layout)
    slide.shapes.title.text = "Introduction"
    slide.placeholders[1].text = "Welcome to the presentation"

    slide2 = prs.slides.add_slide(slide_layout)
    slide2.shapes.title.text = "Methods"
    slide2.placeholders[1].text = "We used advanced techniques"

    f = tmp_path / "test.pptx"
    prs.save(str(f))

    doc = parse_document(f)
    assert doc.source_format == "pptx"
    assert doc.total_pages == 2
    assert "Introduction" in doc.full_markdown
    assert "Methods" in doc.full_markdown


# ---------------------------------------------------------------------------
# WP 3.4: RST
# ---------------------------------------------------------------------------


def test_parse_rst(tmp_path: Path):
    rst_content = """
Title
=====

Introduction
------------

This is a reStructuredText document.

Methods
-------

We use advanced techniques.
"""
    f = tmp_path / "doc.rst"
    f.write_text(rst_content)

    doc = parse_document(f)
    assert doc.source_format == "rst"
    assert doc.total_pages == 1
    assert "reStructuredText" in doc.full_markdown
    assert len(doc.toc) > 0


def test_parse_rst_empty(tmp_path: Path):
    f = tmp_path / "empty.rst"
    f.write_text("")
    doc = parse_document(f)
    assert doc.pages == []


# ---------------------------------------------------------------------------
# WP 3.4: AsciiDoc
# ---------------------------------------------------------------------------


def test_parse_asciidoc(tmp_path: Path):
    adoc_content = """= Document Title

== Introduction

This is an AsciiDoc document.

== Methods

We use *bold* and _italic_ text.
"""
    f = tmp_path / "doc.adoc"
    f.write_text(adoc_content)

    doc = parse_document(f)
    assert doc.source_format == "asciidoc"
    assert doc.total_pages == 1
    assert "AsciiDoc" in doc.full_markdown


def test_parse_asciidoc_empty(tmp_path: Path):
    f = tmp_path / "empty.adoc"
    f.write_text("")
    doc = parse_document(f)
    assert doc.pages == []


def test_parse_asciidoc_headings(tmp_path: Path):
    """AsciiDoc headings convert to markdown headings."""
    f = tmp_path / "headings.adoc"
    f.write_text("= Title\n\n== Chapter\n\n=== Section\n\nContent here.\n")

    doc = parse_document(f)
    md = doc.full_markdown
    assert "# Title" in md
    assert "## Chapter" in md
    assert "### Section" in md


# ---------------------------------------------------------------------------
# General
# ---------------------------------------------------------------------------


def test_supported_formats_include_new():
    """SUPPORTED_FORMATS includes all Phase 3 formats."""
    for ext in [".epub", ".csv", ".xlsx", ".xls", ".pptx", ".rst", ".adoc", ".asciidoc"]:
        assert ext in SUPPORTED_FORMATS, f"{ext} missing from SUPPORTED_FORMATS"


def test_unsupported_format_raises(tmp_path: Path):
    """Unsupported extension raises ValueError."""
    f = tmp_path / "test.xyz"
    f.write_text("data")
    with pytest.raises(ValueError, match="Unsupported format"):
        parse_document(f)
