"""Tests for format parsers (Phase 3 WP 3.1–3.4 and Phase 12-13)."""

from __future__ import annotations

import json
import zipfile
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


# ---------------------------------------------------------------------------
# Phase 12-13: EML, XML, JSON/JSONL, ZIP (Notion/Confluence)
# ---------------------------------------------------------------------------


class TestEMLParser:
    def test_parse_basic_eml(self, tmp_path):
        eml = tmp_path / "test.eml"
        eml.write_text(
            "From: alice@example.com\r\n"
            "To: bob@example.com\r\n"
            "Subject: Test Email\r\n"
            "Date: Mon, 1 Jan 2024 00:00:00 +0000\r\n"
            "Content-Type: text/plain\r\n"
            "\r\n"
            "Hello, this is the body of the email.\r\n"
            "It has multiple lines.\r\n"
        )
        doc = parse_document(eml)
        assert doc.title == "Test Email"
        assert doc.source_format == "eml"
        assert len(doc.pages) == 1
        assert "alice@example.com" in doc.pages[0].markdown
        assert "Hello, this is the body" in doc.pages[0].markdown

    def test_parse_eml_no_subject(self, tmp_path):
        eml = tmp_path / "nosubject.eml"
        eml.write_text(
            "From: alice@example.com\r\n"
            "To: bob@example.com\r\n"
            "Content-Type: text/plain\r\n"
            "\r\n"
            "No subject email.\r\n"
        )
        doc = parse_document(eml)
        assert doc.source_format == "eml"
        assert len(doc.pages) >= 1


class TestXMLParser:
    def test_parse_basic_xml(self, tmp_path):
        xml = tmp_path / "test.xml"
        xml.write_text(
            '<?xml version="1.0"?>\n'
            "<root>\n"
            "  <title>Test Document</title>\n"
            "  <section>\n"
            "    <heading>Introduction</heading>\n"
            "    <content>Some text here</content>\n"
            "  </section>\n"
            "</root>"
        )
        doc = parse_document(xml)
        assert doc.source_format == "xml"
        assert len(doc.pages) == 1
        assert "Test Document" in doc.pages[0].markdown
        assert "Introduction" in doc.pages[0].markdown

    def test_parse_empty_xml(self, tmp_path):
        xml = tmp_path / "empty.xml"
        xml.write_text("")
        doc = parse_document(xml)
        assert doc.pages == []

    def test_parse_malformed_xml(self, tmp_path):
        xml = tmp_path / "bad.xml"
        xml.write_text("<unclosed><tag>content")
        doc = parse_document(xml)
        # Should fall back to code block
        assert len(doc.pages) == 1
        assert "```" in doc.pages[0].markdown or "content" in doc.pages[0].markdown


class TestJSONParser:
    def test_parse_json_object(self, tmp_path):
        jf = tmp_path / "test.json"
        jf.write_text(json.dumps({"name": "Alice", "age": 30, "city": "Berlin"}))
        doc = parse_document(jf)
        assert doc.source_format == "json"
        assert "Alice" in doc.pages[0].markdown
        assert "Berlin" in doc.pages[0].markdown

    def test_parse_json_array(self, tmp_path):
        jf = tmp_path / "list.json"
        jf.write_text(json.dumps([{"id": 1, "name": "A"}, {"id": 2, "name": "B"}]))
        doc = parse_document(jf)
        assert doc.source_format == "json"
        assert len(doc.pages) >= 1

    def test_parse_jsonl(self, tmp_path):
        jf = tmp_path / "data.jsonl"
        jf.write_text('{"id": 1, "text": "first"}\n{"id": 2, "text": "second"}\n')
        doc = parse_document(jf)
        assert doc.source_format == "json"
        assert "first" in doc.pages[0].markdown
        assert "second" in doc.pages[0].markdown

    def test_parse_empty_json(self, tmp_path):
        jf = tmp_path / "empty.json"
        jf.write_text("")
        doc = parse_document(jf)
        assert doc.pages == []


class TestImageParser:
    def test_image_formats_in_supported(self):
        from ingestible.pipeline.stage1_parsing import IMAGE_FORMATS
        for ext in IMAGE_FORMATS:
            assert ext in SUPPORTED_FORMATS, f"{ext} not in SUPPORTED_FORMATS"


class TestZIPParsers:
    def test_parse_notion_zip(self, tmp_path):
        zp = tmp_path / "notion.zip"
        with zipfile.ZipFile(zp, "w") as zf:
            zf.writestr(
                "Page One abc123def456789012345678abcdef01.md",
                "# Page One\n\nContent of page one.",
            )
            zf.writestr(
                "Page Two def456abc789012345678901abcdef02.md",
                "# Page Two\n\nContent of page two.",
            )
        doc = parse_document(zp)
        assert doc.source_format == "notion"
        assert doc.total_pages == 2
        assert "Page One" in doc.pages[0].markdown

    def test_parse_confluence_zip(self, tmp_path):
        zp = tmp_path / "confluence.zip"
        with zipfile.ZipFile(zp, "w") as zf:
            zf.writestr("index.html", "<html><body><h1>Space Home</h1></body></html>")
            zf.writestr(
                "page1.html",
                "<html><body><h1>First Page</h1><p>Some content.</p></body></html>",
            )
        doc = parse_document(zp)
        assert doc.source_format == "confluence"
        assert doc.total_pages >= 1

    def test_parse_generic_zip(self, tmp_path):
        zp = tmp_path / "mixed.zip"
        with zipfile.ZipFile(zp, "w") as zf:
            zf.writestr("readme.txt", "Hello World")
            zf.writestr("notes.txt", "Some plain text notes")
        doc = parse_document(zp)
        assert doc.source_format == "zip"
        assert doc.total_pages == 2

    def test_parse_empty_zip(self, tmp_path):
        zp = tmp_path / "empty.zip"
        with zipfile.ZipFile(zp, "w"):
            pass
        doc = parse_document(zp)
        assert doc.pages == []
