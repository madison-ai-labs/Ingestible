"""Stage 1 — Document Parsing.

Supported formats: PDF, Markdown, plain text, DOCX, HTML, EPUB,
CSV, Excel, PowerPoint, RST, AsciiDoc.
PDF: Primary Docling (IBM), fallback PyMuPDF4LLM, OCR retry.
DOCX: python-docx. HTML: markdownify. Markdown/TXT: direct read.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from ingestible.models.document import PageContent, ParsedDocument, TOCEntry

logger = logging.getLogger(__name__)

CHARS_PER_PAGE_THRESHOLD = 100
SUPPORTED_FORMATS = {
    ".pdf", ".md", ".txt", ".docx", ".html", ".htm",
    ".epub", ".csv", ".xlsx", ".xls", ".pptx",
    ".rst", ".adoc", ".asciidoc",
}


def parse_document(file_path: str | Path, force_ocr: bool = False) -> ParsedDocument:
    """Parse a document into structured markdown. Auto-detects format from extension."""
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    ext = file_path.suffix.lower()
    if ext not in SUPPORTED_FORMATS:
        raise ValueError(
            f"Unsupported format '{ext}'. Supported: {sorted(SUPPORTED_FORMATS)}"
        )

    if ext == ".pdf":
        return parse_pdf(file_path, force_ocr=force_ocr)
    elif ext == ".md":
        return _parse_markdown(file_path)
    elif ext == ".txt":
        return _parse_plaintext(file_path)
    elif ext == ".docx":
        return _parse_docx(file_path)
    elif ext in (".html", ".htm"):
        return _parse_html(file_path)
    elif ext == ".epub":
        return _parse_epub(file_path)
    elif ext == ".csv":
        return _parse_csv(file_path)
    elif ext in (".xlsx", ".xls"):
        return _parse_excel(file_path)
    elif ext == ".pptx":
        return _parse_pptx(file_path)
    elif ext == ".rst":
        return _parse_rst(file_path)
    elif ext in (".adoc", ".asciidoc"):
        return _parse_asciidoc(file_path)

    raise ValueError(f"Unsupported format: {ext}")  # unreachable, but defensive


def parse_pdf(pdf_path: str | Path, force_ocr: bool = False) -> ParsedDocument:
    """Parse a PDF into structured markdown. Tries Docling first, falls back to PyMuPDF4LLM."""
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    doc = _try_docling(pdf_path, ocr=force_ocr)
    if doc is None:
        logger.warning("Docling failed, falling back to PyMuPDF4LLM")
        doc = _try_pymupdf(pdf_path)

    if doc is None:
        raise RuntimeError(f"All parsers failed for {pdf_path}")

    # OCR retry: if text is too sparse, re-parse with OCR
    if not force_ocr and doc.avg_chars_per_page < CHARS_PER_PAGE_THRESHOLD:
        logger.info(
            "Sparse text detected (%.0f chars/page avg), retrying with OCR",
            doc.avg_chars_per_page,
        )
        ocr_doc = _try_docling(pdf_path, ocr=True)
        if ocr_doc is not None and ocr_doc.avg_chars_per_page > doc.avg_chars_per_page:
            doc = ocr_doc

    logger.info(
        "Parsed %s: %d pages, %.0f avg chars/page",
        pdf_path.name,
        doc.total_pages,
        doc.avg_chars_per_page,
    )
    return doc


def _try_docling(pdf_path: Path, ocr: bool = False) -> ParsedDocument | None:
    try:
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.document_converter import DocumentConverter, PdfFormatOption

        pipeline_opts = PdfPipelineOptions(do_ocr=ocr)
        converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_opts)
            }
        )
        result = converter.convert(str(pdf_path))
        doc_obj = result.document

        # Get real page count from docling
        num_pages = doc_obj.num_pages()

        # Export full markdown
        full_md = doc_obj.export_to_markdown()

        # Extract TOC from document if available
        toc = _extract_toc_from_markdown(full_md)

        # Split markdown into per-page approximations
        pages = _split_into_pages(full_md, num_pages)

        title = _detect_title(full_md, pdf_path)

        return ParsedDocument(
            title=title,
            source_path=str(pdf_path),
            total_pages=num_pages,
            toc=toc,
            pages=pages,
        )
    except Exception:
        logger.debug("Docling parsing failed", exc_info=True)
        return None


def _try_pymupdf(pdf_path: Path) -> ParsedDocument | None:
    try:
        import pymupdf4llm

        md_pages = pymupdf4llm.to_markdown(str(pdf_path), page_chunks=True)

        pages = []
        for i, page_data in enumerate(md_pages):
            md_text = page_data if isinstance(page_data, str) else page_data.get("text", "")
            pages.append(
                PageContent(
                    page_num=i + 1,
                    markdown=md_text,
                    has_code_blocks="```" in md_text,
                )
            )

        full_md = "\n\n".join(p.markdown for p in pages)
        toc = _extract_toc_from_markdown(full_md)
        title = _detect_title(full_md, pdf_path)

        return ParsedDocument(
            title=title,
            source_path=str(pdf_path),
            total_pages=len(pages),
            toc=toc,
            pages=pages,
        )
    except Exception:
        logger.debug("PyMuPDF4LLM parsing failed", exc_info=True)
        return None


def _extract_toc_from_markdown(md: str) -> list[TOCEntry]:
    """Extract a table of contents from markdown headings."""
    entries = []
    for line in md.split("\n"):
        m = re.match(r"^(#{1,6})\s+(.+)$", line)
        if m:
            level = len(m.group(1))
            title = m.group(2).strip()
            entries.append(TOCEntry(level=level, title=title))
    return entries


def _split_into_pages(md: str, num_pages: int = 0) -> list[PageContent]:
    """Split a monolithic markdown string into page-like chunks.

    Docling doesn't always give per-page output, so we approximate
    by splitting on page break markers, or distribute evenly across
    the known page count.
    """
    # Try page-break markers first (some converters emit these)
    page_break = re.split(r"\n---\s*PAGE\s+\d+\s*---\n|\f", md)
    if len(page_break) > 1:
        parts = page_break
    elif num_pages > 1:
        # Distribute content evenly across known page count
        # Split on heading boundaries first, then distribute
        sections = re.split(r"(?=\n#{1,6}\s)", md)
        parts = _distribute_sections(sections, num_pages)
    else:
        parts = [md]

    pages = []
    for i, part in enumerate(parts):
        text = part.strip()
        if not text:
            continue
        pages.append(
            PageContent(
                page_num=i + 1,
                markdown=text,
                has_code_blocks="```" in text,
            )
        )
    return pages


def _distribute_sections(sections: list[str], num_pages: int) -> list[str]:
    """Distribute markdown sections across N pages roughly evenly by character count."""
    total_chars = sum(len(s) for s in sections)
    chars_per_page = total_chars / num_pages if num_pages > 0 else total_chars

    pages: list[str] = []
    current = ""
    current_chars = 0

    for section in sections:
        current += section
        current_chars += len(section)

        if current_chars >= chars_per_page and len(pages) < num_pages - 1:
            pages.append(current)
            current = ""
            current_chars = 0

    # Flush remainder
    if current:
        pages.append(current)

    return pages


def _detect_title(md: str, file_path: Path) -> str:
    """Try to detect the document title from the first heading or filename."""
    for line in md.split("\n")[:20]:
        m = re.match(r"^#\s+(.+)$", line)
        if m:
            return m.group(1).strip()
    return file_path.stem.replace("_", " ").replace("-", " ").title()


# ---------------------------------------------------------------------------
# Non-PDF format parsers
# ---------------------------------------------------------------------------


def _parse_markdown(file_path: Path) -> ParsedDocument:
    """Parse a Markdown file. It's already markdown — extract TOC and title."""
    text = file_path.read_text(errors="replace").strip()
    if not text:
        return ParsedDocument(
            title=file_path.stem, source_path=str(file_path),
            source_format="md", pages=[],
        )

    toc = _extract_toc_from_markdown(text)
    title = _detect_title(text, file_path)
    page = PageContent(page_num=1, markdown=text, has_code_blocks="```" in text)

    return ParsedDocument(
        title=title,
        source_path=str(file_path),
        source_format="md",
        total_pages=1,
        toc=toc,
        pages=[page],
    )


def _parse_plaintext(file_path: Path) -> ParsedDocument:
    """Parse a plain text file. Title from first non-empty line or filename."""
    text = file_path.read_text(errors="replace").strip()
    if not text:
        return ParsedDocument(
            title=file_path.stem, source_path=str(file_path),
            source_format="txt", pages=[],
        )

    # Title: first non-empty line, capped at 100 chars
    first_line = ""
    for line in text.split("\n"):
        line = line.strip()
        if line:
            first_line = line[:100]
            break
    title = first_line or file_path.stem.replace("_", " ").replace("-", " ").title()

    page = PageContent(page_num=1, markdown=text)

    return ParsedDocument(
        title=title,
        source_path=str(file_path),
        source_format="txt",
        total_pages=1,
        pages=[page],
    )


def _parse_docx(file_path: Path) -> ParsedDocument:
    """Parse a DOCX file using python-docx. Maps heading styles to markdown."""
    from docx import Document as DocxDocument
    from docx.table import Table

    doc = DocxDocument(str(file_path))
    md_parts: list[str] = []

    for element in doc.element.body:
        tag = element.tag.split("}")[-1]  # strip namespace

        if tag == "p":
            # Find the matching paragraph object
            for para in doc.paragraphs:
                if para._element is element:
                    text = para.text.strip()
                    if not text:
                        break
                    style_name = (para.style.name or "").lower()
                    if style_name.startswith("heading"):
                        # Extract heading level from style name (e.g. "Heading 2")
                        level_match = re.search(r"(\d+)", style_name)
                        level = int(level_match.group(1)) if level_match else 1
                        level = min(level, 6)
                        md_parts.append(f"{'#' * level} {text}")
                    else:
                        md_parts.append(text)
                    break

        elif tag == "tbl":
            # Find the matching table object
            for table in doc.tables:
                if table._element is element:
                    md_parts.append(_table_to_markdown(table))
                    break

    full_md = "\n\n".join(md_parts).strip()

    if not full_md:
        return ParsedDocument(
            title=file_path.stem, source_path=str(file_path),
            source_format="docx", pages=[],
        )

    toc = _extract_toc_from_markdown(full_md)
    title = _detect_title(full_md, file_path)
    page = PageContent(page_num=1, markdown=full_md, has_code_blocks="```" in full_md)

    return ParsedDocument(
        title=title,
        source_path=str(file_path),
        source_format="docx",
        total_pages=1,
        toc=toc,
        pages=[page],
    )


def _table_to_markdown(table) -> str:
    """Convert a python-docx Table to a pipe-delimited markdown table."""
    rows = []
    for row in table.rows:
        cells = [cell.text.strip().replace("|", "\\|") for cell in row.cells]
        rows.append("| " + " | ".join(cells) + " |")
    if len(rows) >= 1:
        # Insert separator after header row
        col_count = len(table.rows[0].cells)
        sep = "| " + " | ".join(["---"] * col_count) + " |"
        rows.insert(1, sep)
    return "\n".join(rows)


def _parse_html(file_path: Path) -> ParsedDocument:
    """Parse an HTML file by converting to markdown via markdownify."""
    from markdownify import markdownify

    html = file_path.read_text(errors="replace").strip()
    if not html:
        return ParsedDocument(
            title=file_path.stem, source_path=str(file_path),
            source_format="html", pages=[],
        )

    # Remove <script> and <style> elements entirely (tag + content)
    html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)

    md = markdownify(html, heading_style="ATX").strip()

    if not md:
        return ParsedDocument(
            title=file_path.stem, source_path=str(file_path),
            source_format="html", pages=[],
        )

    toc = _extract_toc_from_markdown(md)
    title = _detect_title(md, file_path)
    page = PageContent(page_num=1, markdown=md, has_code_blocks="```" in md)

    return ParsedDocument(
        title=title,
        source_path=str(file_path),
        source_format="html",
        total_pages=1,
        toc=toc,
        pages=[page],
    )


# ---------------------------------------------------------------------------
# Phase 3 format parsers (WP 3.1–3.4)
# ---------------------------------------------------------------------------


def _parse_epub(file_path: Path) -> ParsedDocument:
    """Parse an EPUB file. Extracts chapters as HTML, converts to markdown."""
    from ebooklib import epub
    from markdownify import markdownify

    book = epub.read_epub(str(file_path), options={"ignore_ncx": True})
    md_parts: list[str] = []
    pages: list[PageContent] = []

    page_num = 0
    for item in book.get_items_of_type(9):  # ITEM_DOCUMENT = 9
        html = item.get_content().decode("utf-8", errors="replace")
        # Strip scripts/styles
        html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)
        md = markdownify(html, heading_style="ATX").strip()
        if not md:
            continue
        page_num += 1
        md_parts.append(md)
        pages.append(
            PageContent(page_num=page_num, markdown=md, has_code_blocks="```" in md)
        )

    full_md = "\n\n".join(md_parts)
    if not full_md:
        return ParsedDocument(
            title=file_path.stem, source_path=str(file_path),
            source_format="epub", pages=[],
        )

    toc = _extract_toc_from_markdown(full_md)
    title = _detect_title(full_md, file_path)

    return ParsedDocument(
        title=title,
        source_path=str(file_path),
        source_format="epub",
        total_pages=len(pages),
        toc=toc,
        pages=pages,
    )


def _parse_csv(file_path: Path) -> ParsedDocument:
    """Parse a CSV file. Converts to a markdown table."""
    import csv
    import io

    text = file_path.read_text(errors="replace")
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)

    if not rows:
        return ParsedDocument(
            title=file_path.stem, source_path=str(file_path),
            source_format="csv", pages=[],
        )

    # Convert to markdown table
    md_lines: list[str] = []
    header = rows[0]
    md_lines.append("| " + " | ".join(c.replace("|", "\\|") for c in header) + " |")
    md_lines.append("| " + " | ".join("---" for _ in header) + " |")

    # Split large CSVs into page-sized chunks (~50 rows per page)
    ROWS_PER_PAGE = 50
    pages: list[PageContent] = []
    page_rows: list[str] = list(md_lines)  # start with header

    for i, row in enumerate(rows[1:], 1):
        page_rows.append("| " + " | ".join(c.replace("|", "\\|") for c in row) + " |")
        if i % ROWS_PER_PAGE == 0:
            pages.append(PageContent(page_num=len(pages) + 1, markdown="\n".join(page_rows)))
            page_rows = list(md_lines)  # restart with header

    if page_rows != md_lines:  # flush remaining rows
        pages.append(PageContent(page_num=len(pages) + 1, markdown="\n".join(page_rows)))

    title = file_path.stem.replace("_", " ").replace("-", " ").title()

    return ParsedDocument(
        title=title,
        source_path=str(file_path),
        source_format="csv",
        total_pages=len(pages),
        pages=pages,
    )


def _parse_excel(file_path: Path) -> ParsedDocument:
    """Parse an Excel file. Each sheet becomes pages of markdown tables."""
    from openpyxl import load_workbook

    wb = load_workbook(str(file_path), read_only=True, data_only=True)
    pages: list[PageContent] = []

    for sheet in wb.sheetnames:
        ws = wb[sheet]
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            continue

        # Build markdown table
        header = [str(c) if c is not None else "" for c in rows[0]]
        md_lines = [
            f"## {sheet}",
            "",
            "| " + " | ".join(h.replace("|", "\\|") for h in header) + " |",
            "| " + " | ".join("---" for _ in header) + " |",
        ]

        for row in rows[1:]:
            cells = [str(c).replace("|", "\\|") if c is not None else "" for c in row]
            md_lines.append("| " + " | ".join(cells) + " |")

        pages.append(
            PageContent(page_num=len(pages) + 1, markdown="\n".join(md_lines))
        )

    wb.close()

    if not pages:
        return ParsedDocument(
            title=file_path.stem, source_path=str(file_path),
            source_format="xlsx", pages=[],
        )

    full_md = "\n\n".join(p.markdown for p in pages)
    toc = _extract_toc_from_markdown(full_md)
    title = file_path.stem.replace("_", " ").replace("-", " ").title()

    return ParsedDocument(
        title=title,
        source_path=str(file_path),
        source_format="xlsx",
        total_pages=len(pages),
        toc=toc,
        pages=pages,
    )


def _parse_pptx(file_path: Path) -> ParsedDocument:
    """Parse a PowerPoint file. Each slide = one PageContent."""
    from pptx import Presentation

    prs = Presentation(str(file_path))
    pages: list[PageContent] = []

    for slide_num, slide in enumerate(prs.slides, 1):
        md_parts: list[str] = []

        # Title
        if slide.shapes.title and slide.shapes.title.text.strip():
            md_parts.append(f"## {slide.shapes.title.text.strip()}")

        # Text from all shapes
        for shape in slide.shapes:
            if shape == slide.shapes.title:
                continue
            if shape.has_text_frame:
                for para in shape.text_frame.paragraphs:
                    text = para.text.strip()
                    if not text:
                        continue
                    # Detect bullet lists (indented paragraphs)
                    if para.level > 0:
                        md_parts.append(f"{'  ' * para.level}- {text}")
                    else:
                        md_parts.append(text)
            if shape.has_table:
                md_parts.append(_shape_table_to_md(shape.table))

        md = "\n\n".join(md_parts).strip()
        if md:
            pages.append(PageContent(page_num=slide_num, markdown=md))

    if not pages:
        return ParsedDocument(
            title=file_path.stem, source_path=str(file_path),
            source_format="pptx", pages=[],
        )

    full_md = "\n\n".join(p.markdown for p in pages)
    toc = _extract_toc_from_markdown(full_md)
    title = _detect_title(full_md, file_path)

    return ParsedDocument(
        title=title,
        source_path=str(file_path),
        source_format="pptx",
        total_pages=len(pages),
        toc=toc,
        pages=pages,
    )


def _shape_table_to_md(table) -> str:
    """Convert a python-pptx Table to markdown."""
    rows = []
    for row in table.rows:
        cells = [cell.text.strip().replace("|", "\\|") for cell in row.cells]
        rows.append("| " + " | ".join(cells) + " |")
    if rows:
        col_count = len(table.rows[0].cells)
        sep = "| " + " | ".join(["---"] * col_count) + " |"
        rows.insert(1, sep)
    return "\n".join(rows)


def _parse_rst(file_path: Path) -> ParsedDocument:
    """Parse reStructuredText. Converts RST → HTML → markdown."""
    from docutils.core import publish_string
    from markdownify import markdownify

    rst_text = file_path.read_text(errors="replace")
    if not rst_text.strip():
        return ParsedDocument(
            title=file_path.stem, source_path=str(file_path),
            source_format="rst", pages=[],
        )

    # RST → HTML
    html = publish_string(rst_text, writer="html").decode("utf-8", errors="replace")
    # HTML → Markdown
    md = markdownify(html, heading_style="ATX").strip()

    if not md:
        return ParsedDocument(
            title=file_path.stem, source_path=str(file_path),
            source_format="rst", pages=[],
        )

    toc = _extract_toc_from_markdown(md)
    title = _detect_title(md, file_path)
    page = PageContent(page_num=1, markdown=md, has_code_blocks="```" in md)

    return ParsedDocument(
        title=title,
        source_path=str(file_path),
        source_format="rst",
        total_pages=1,
        toc=toc,
        pages=[page],
    )


def _parse_asciidoc(file_path: Path) -> ParsedDocument:
    """Parse AsciiDoc. Tries asciidoctor subprocess, falls back to regex conversion."""
    text = file_path.read_text(errors="replace")
    if not text.strip():
        return ParsedDocument(
            title=file_path.stem, source_path=str(file_path),
            source_format="asciidoc", pages=[],
        )

    md = _asciidoc_to_markdown(text)

    toc = _extract_toc_from_markdown(md)
    title = _detect_title(md, file_path)
    page = PageContent(page_num=1, markdown=md, has_code_blocks="```" in md)

    return ParsedDocument(
        title=title,
        source_path=str(file_path),
        source_format="asciidoc",
        total_pages=1,
        toc=toc,
        pages=[page],
    )


def _asciidoc_to_markdown(text: str) -> str:
    """Convert AsciiDoc to Markdown via asciidoctor or regex fallback."""
    # Try asciidoctor subprocess
    try:
        import subprocess

        result = subprocess.run(
            ["asciidoctor", "-b", "html5", "-o", "-", "-"],
            input=text,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            from markdownify import markdownify

            return markdownify(result.stdout, heading_style="ATX").strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Regex fallback: convert common AsciiDoc patterns to Markdown
    md = text
    # Headings: = Title → # Title, == Heading → ## Heading
    md = re.sub(r"^={5}\s+(.+)$", r"##### \1", md, flags=re.MULTILINE)
    md = re.sub(r"^={4}\s+(.+)$", r"#### \1", md, flags=re.MULTILINE)
    md = re.sub(r"^={3}\s+(.+)$", r"### \1", md, flags=re.MULTILINE)
    md = re.sub(r"^={2}\s+(.+)$", r"## \1", md, flags=re.MULTILINE)
    md = re.sub(r"^=\s+(.+)$", r"# \1", md, flags=re.MULTILINE)
    # Bold: *text* → **text** (but not list items)
    md = re.sub(r"(?<!\w)\*(\S.*?\S)\*(?!\w)", r"**\1**", md)
    # Italic: _text_ → *text*
    md = re.sub(r"(?<!\w)_(\S.*?\S)_(?!\w)", r"*\1*", md)
    # Code blocks: ---- → ```
    md = re.sub(r"^----+$", "```", md, flags=re.MULTILINE)
    # Links: link:url[text] → [text](url)
    md = re.sub(r"link:(\S+)\[([^\]]*)\]", r"[\2](\1)", md)

    return md.strip()
