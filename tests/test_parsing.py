"""Tests for multi-format document parsing (Stage 1)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from ingestible.pipeline.stage1_parsing import parse_document


def test_parse_markdown(tmp_path):
    md_file = tmp_path / "sample.md"
    md_file.write_text("# My Title\n\nFirst paragraph.\n\n## Section\n\nSecond paragraph.")

    doc = parse_document(md_file)

    assert doc.title == "My Title"
    assert doc.source_format == "md"
    assert len(doc.pages) == 1
    assert "First paragraph" in doc.pages[0].markdown
    assert len(doc.toc) == 2  # "# My Title" and "## Section"
    assert doc.toc[0].level == 1
    assert doc.toc[1].level == 2
    assert doc.toc[1].title == "Section"


def test_parse_plaintext(tmp_path):
    txt_file = tmp_path / "readme.txt"
    txt_file.write_text("Welcome to the project\n\nThis is a description.\nMore details here.")

    doc = parse_document(txt_file)

    assert doc.title == "Welcome to the project"
    assert doc.source_format == "txt"
    assert len(doc.pages) == 1
    assert "description" in doc.pages[0].markdown


def test_parse_plaintext_title_capped(tmp_path):
    txt_file = tmp_path / "long.txt"
    long_line = "A" * 200
    txt_file.write_text(long_line + "\n\nBody text.")

    doc = parse_document(txt_file)

    assert len(doc.title) == 100


def test_parse_docx(tmp_path):
    from docx import Document as DocxDocument

    docx_path = tmp_path / "sample.docx"
    docx_doc = DocxDocument()
    docx_doc.add_heading("Chapter One", level=1)
    docx_doc.add_paragraph("This is the first paragraph.")
    docx_doc.add_heading("Sub Section", level=2)
    docx_doc.add_paragraph("Another paragraph here.")
    # Add a table
    table = docx_doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Header A"
    table.cell(0, 1).text = "Header B"
    table.cell(1, 0).text = "Cell 1"
    table.cell(1, 1).text = "Cell 2"
    docx_doc.save(str(docx_path))

    doc = parse_document(docx_path)

    assert doc.source_format == "docx"
    assert doc.title == "Chapter One"
    assert len(doc.pages) == 1
    md = doc.pages[0].markdown
    assert "# Chapter One" in md
    assert "## Sub Section" in md
    assert "Header A" in md
    assert "Cell 1" in md
    # TOC should have 2 entries
    assert len(doc.toc) == 2


def test_parse_html(tmp_path):
    html_file = tmp_path / "page.html"
    html_file.write_text(
        "<html><head><title>Test</title></head><body>"
        "<h1>Main Heading</h1>"
        "<p>Some text here.</p>"
        "<table><tr><th>Col A</th><th>Col B</th></tr>"
        "<tr><td>1</td><td>2</td></tr></table>"
        "<script>alert('x')</script>"
        "</body></html>"
    )

    doc = parse_document(html_file)

    assert doc.source_format == "html"
    assert doc.title == "Main Heading"
    assert len(doc.pages) == 1
    md = doc.pages[0].markdown
    assert "Main Heading" in md
    assert "Some text" in md
    # Script tags should be stripped
    assert "alert" not in md


def test_parse_htm_extension(tmp_path):
    htm_file = tmp_path / "page.htm"
    htm_file.write_text("<html><body><h1>HTM Page</h1><p>Content.</p></body></html>")

    doc = parse_document(htm_file)

    assert doc.source_format == "html"
    assert doc.title == "HTM Page"


def test_parse_empty_file_md(tmp_path):
    f = tmp_path / "empty.md"
    f.write_text("")
    doc = parse_document(f)
    assert doc.pages == []
    assert doc.source_format == "md"


def test_parse_empty_file_txt(tmp_path):
    f = tmp_path / "empty.txt"
    f.write_text("")
    doc = parse_document(f)
    assert doc.pages == []
    assert doc.source_format == "txt"


def test_parse_empty_file_html(tmp_path):
    f = tmp_path / "empty.html"
    f.write_text("")
    doc = parse_document(f)
    assert doc.pages == []
    assert doc.source_format == "html"


def test_parse_empty_file_docx(tmp_path):
    from docx import Document as DocxDocument

    docx_path = tmp_path / "empty.docx"
    DocxDocument().save(str(docx_path))
    doc = parse_document(docx_path)
    assert doc.pages == []
    assert doc.source_format == "docx"


def test_parse_unsupported_format(tmp_path):
    xyz_file = tmp_path / "data.xyz"
    xyz_file.write_text("some data")

    with pytest.raises(ValueError, match="Unsupported format"):
        parse_document(xyz_file)


def test_parse_file_not_found():
    with pytest.raises(FileNotFoundError):
        parse_document("/nonexistent/file.md")


@patch("ingestible.pipeline.stage1_parsing.parse_pdf")
def test_parse_document_routes_pdf(mock_parse_pdf, tmp_path):
    pdf_file = tmp_path / "test.pdf"
    pdf_file.write_bytes(b"%PDF-1.4 fake")  # just needs to exist

    from ingestible.models.document import ParsedDocument

    mock_parse_pdf.return_value = ParsedDocument(
        title="Mock PDF", source_path=str(pdf_file), source_format="pdf"
    )

    doc = parse_document(pdf_file)

    mock_parse_pdf.assert_called_once_with(pdf_file, force_ocr=False)
    assert doc.title == "Mock PDF"
    assert doc.source_format == "pdf"
