"""Stage 1 — Document Parsing.

Supported formats: PDF, Markdown, plain text, DOCX, HTML.
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
SUPPORTED_FORMATS = {".pdf", ".md", ".txt", ".docx", ".html", ".htm"}


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
