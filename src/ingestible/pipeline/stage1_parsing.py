"""Stage 1 — Document Parsing.

Supported formats: PDF, Markdown, plain text, DOCX, HTML, EPUB,
CSV, Excel, PowerPoint, RST, AsciiDoc, images (PNG/JPEG/TIFF/BMP/WebP),
email (EML/MSG), XML, JSON/JSONL, ZIP archives (Notion / Confluence exports).
PDF: Primary Docling (IBM), fallback PyMuPDF4LLM, OCR retry.
DOCX: python-docx. HTML: markdownify. Markdown/TXT: direct read.
Images: Docling VLM pipeline (OCR + layout). Email: stdlib email / extract-msg.
XML/JSON: stdlib parsers with markdown conversion.
ZIP: auto-detects Notion (.md with UUIDs) vs Confluence (HTML with index.html).
"""

from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from pathlib import Path

from ingestible.models.document import FigureRef, PageContent, ParsedDocument, TOCEntry

logger = logging.getLogger(__name__)

CHARS_PER_PAGE_THRESHOLD = 100
IMAGE_FORMATS = {".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".webp"}

SUPPORTED_FORMATS = {
    ".pdf",
    ".md",
    ".txt",
    ".docx",
    ".html",
    ".htm",
    ".epub",
    ".csv",
    ".xlsx",
    ".xls",
    ".pptx",
    ".rst",
    ".adoc",
    ".asciidoc",
    # Images
    *IMAGE_FORMATS,
    # Email
    ".eml",
    ".msg",
    # Structured data
    ".xml",
    ".json",
    ".jsonl",
    # Audio
    ".mp3",
    ".wav",
    ".m4a",
    ".flac",
    ".ogg",
    ".wma",
    ".aac",
    ".opus",
    # Video
    ".mp4",
    ".mkv",
    ".avi",
    ".mov",
    ".webm",
    ".wmv",
    ".flv",
    # Archives (Notion / Confluence exports)
    ".zip",
    # Source code
    *{
        ".py",
        ".pyw",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".mjs",
        ".cjs",
        ".go",
        ".rs",
        ".java",
        ".kt",
        ".kts",
        ".c",
        ".cpp",
        ".cc",
        ".cxx",
        ".h",
        ".hpp",
        ".cs",
        ".rb",
        ".swift",
        ".scala",
    },
}

AUDIO_FORMATS = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".wma", ".aac", ".opus"}
VIDEO_FORMATS = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".wmv", ".flv"}
CODE_FORMATS = {
    ".py",
    ".pyw",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".kts",
    ".c",
    ".cpp",
    ".cc",
    ".cxx",
    ".h",
    ".hpp",
    ".cs",
    ".rb",
    ".swift",
    ".scala",
}


def _with_timeout(func, *args, timeout: int = 300, **kwargs):
    """Run a function with a timeout. Raises TimeoutError if it exceeds the limit."""
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(func, *args, **kwargs)
        try:
            return future.result(timeout=timeout)
        except FuturesTimeoutError:
            raise TimeoutError(
                f"Parsing timed out after {timeout}s — the file may be corrupted or too complex"
            )


def parse_document(
    file_path: str | Path, force_ocr: bool = False, timeout: int = 300
) -> ParsedDocument:
    """Parse a document into structured markdown. Auto-detects format from extension."""
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    ext = file_path.suffix.lower()
    if ext not in SUPPORTED_FORMATS:
        raise ValueError(f"Unsupported format '{ext}'. Supported: {sorted(SUPPORTED_FORMATS)}")

    if ext == ".pdf":
        return _with_timeout(parse_pdf, file_path, force_ocr=force_ocr, timeout=timeout)
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
    elif ext in IMAGE_FORMATS:
        return _with_timeout(_parse_image, file_path, timeout=timeout)
    elif ext == ".eml":
        return _parse_eml(file_path)
    elif ext == ".msg":
        return _parse_msg(file_path)
    elif ext == ".xml":
        return _parse_xml(file_path)
    elif ext in (".json", ".jsonl"):
        return _parse_json(file_path)
    elif ext in AUDIO_FORMATS:
        return _with_timeout(_parse_audio, file_path, timeout=timeout)
    elif ext in VIDEO_FORMATS:
        return _with_timeout(_parse_video, file_path, timeout=timeout)
    elif ext == ".zip":
        return _parse_zip_archive(file_path)
    elif ext in CODE_FORMATS:
        return _parse_code_file(file_path)

    raise ValueError(f"Unsupported format: {ext}")  # unreachable, but defensive


def _parse_code_file(file_path: Path) -> ParsedDocument:
    """Parse a source code file. Wraps entire content in a single page with code metadata."""
    content = file_path.read_text(encoding="utf-8", errors="replace")
    return ParsedDocument(
        title=file_path.name,
        source_path=str(file_path),
        source_format="code",
        total_pages=1,
        pages=[
            PageContent(
                page_num=1,
                markdown=content,
                has_code_blocks=True,
            )
        ],
    )


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
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_opts)}
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

        # Extract figures from Docling pictures
        figures = _extract_docling_figures(doc_obj)
        if figures:
            # Attach figures to their respective pages (or first page)
            page_map = {p.page_num: p for p in pages}
            for fig in figures:
                target_page = page_map.get(fig.page_num or 1) or (pages[0] if pages else None)
                if target_page:
                    target_page.figures.append(fig)

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


def _extract_docling_figures(doc_obj) -> list[FigureRef]:
    """Extract figure references from a Docling document object."""
    figures: list[FigureRef] = []
    try:
        pictures = getattr(doc_obj, "pictures", None)
        if not pictures:
            return figures

        for idx, pic in enumerate(pictures):
            fig_id = f"fig-{idx + 1}"
            caption = ""
            if hasattr(pic, "captions") and pic.captions:
                caption = (
                    pic.captions[0].text
                    if hasattr(pic.captions[0], "text")
                    else str(pic.captions[0])
                )
            label = getattr(pic, "label", "") or ""
            classification = getattr(pic, "classification", "") or ""

            # Determine page number from provenance
            page_num = None
            prov = getattr(pic, "prov", None)
            if prov and len(prov) > 0:
                page_num = getattr(prov[0], "page_no", None) or getattr(prov[0], "page", None)

            # Determine image filename
            image_ref = getattr(pic, "image", None)
            uri = getattr(image_ref, "uri", None) if image_ref else None
            if uri:
                ext = Path(uri).suffix or ".png"
                filename = f"{fig_id}{ext}"
            else:
                filename = f"{fig_id}.png"

            figures.append(
                FigureRef(
                    figure_id=fig_id,
                    filename=filename,
                    caption=caption,
                    label=str(label),
                    page_num=page_num,
                    classification=str(classification),
                )
            )
    except Exception:
        logger.debug("Figure extraction failed", exc_info=True)

    return figures


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
            title=file_path.stem,
            source_path=str(file_path),
            source_format="md",
            pages=[],
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
            title=file_path.stem,
            source_path=str(file_path),
            source_format="txt",
            pages=[],
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
            title=file_path.stem,
            source_path=str(file_path),
            source_format="docx",
            pages=[],
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
            title=file_path.stem,
            source_path=str(file_path),
            source_format="html",
            pages=[],
        )

    # Remove <script> and <style> elements entirely (tag + content)
    html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)

    md = markdownify(html, heading_style="ATX").strip()

    if not md:
        return ParsedDocument(
            title=file_path.stem,
            source_path=str(file_path),
            source_format="html",
            pages=[],
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
        pages.append(PageContent(page_num=page_num, markdown=md, has_code_blocks="```" in md))

    full_md = "\n\n".join(md_parts)
    if not full_md:
        return ParsedDocument(
            title=file_path.stem,
            source_path=str(file_path),
            source_format="epub",
            pages=[],
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
            title=file_path.stem,
            source_path=str(file_path),
            source_format="csv",
            pages=[],
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

        pages.append(PageContent(page_num=len(pages) + 1, markdown="\n".join(md_lines)))

    wb.close()

    if not pages:
        return ParsedDocument(
            title=file_path.stem,
            source_path=str(file_path),
            source_format="xlsx",
            pages=[],
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
            title=file_path.stem,
            source_path=str(file_path),
            source_format="pptx",
            pages=[],
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
            title=file_path.stem,
            source_path=str(file_path),
            source_format="rst",
            pages=[],
        )

    # RST → HTML
    html = publish_string(rst_text, writer="html").decode("utf-8", errors="replace")
    # HTML → Markdown
    md = markdownify(html, heading_style="ATX").strip()

    if not md:
        return ParsedDocument(
            title=file_path.stem,
            source_path=str(file_path),
            source_format="rst",
            pages=[],
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
            title=file_path.stem,
            source_path=str(file_path),
            source_format="asciidoc",
            pages=[],
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


# ---------------------------------------------------------------------------
# Image parser
# ---------------------------------------------------------------------------


def _parse_image(file_path: Path) -> ParsedDocument:
    """Parse an image file via Docling's VLM pipeline (OCR + layout analysis)."""
    doc = _try_docling(file_path, ocr=True)
    if doc is None:
        # Fallback: basic OCR description
        logger.warning("Docling failed for image, creating minimal document")
        return ParsedDocument(
            title=file_path.stem,
            source_path=str(file_path),
            source_format="image",
            total_pages=1,
            pages=[PageContent(page_num=1, markdown=f"[Image: {file_path.name}]")],
        )
    doc.source_format = "image"
    return doc


# ---------------------------------------------------------------------------
# Email parsers
# ---------------------------------------------------------------------------


def _parse_eml(file_path: Path) -> ParsedDocument:
    """Parse an EML email file. Extracts headers, body, and attachment names."""
    import email
    from email import policy

    raw = file_path.read_bytes()
    msg = email.message_from_bytes(raw, policy=policy.default)

    md_parts: list[str] = []

    # Headers
    subject = msg.get("Subject", "")
    from_addr = msg.get("From", "")
    to_addr = msg.get("To", "")
    date = msg.get("Date", "")

    md_parts.append(f"# {subject or 'Untitled Email'}")
    md_parts.append(f"**From:** {from_addr}")
    md_parts.append(f"**To:** {to_addr}")
    if date:
        md_parts.append(f"**Date:** {date}")
    md_parts.append("---")

    # Body
    body = msg.get_body(preferencelist=("plain", "html"))
    if body:
        content = body.get_content()
        content_type = body.get_content_type()
        if content_type == "text/html":
            try:
                from markdownify import markdownify

                content = markdownify(content, heading_style="ATX").strip()
            except Exception:
                pass
        md_parts.append(content.strip())

    # Attachments list
    attachments = []
    for part in msg.iter_attachments():
        filename = part.get_filename() or "unnamed"
        attachments.append(filename)
    if attachments:
        md_parts.append("\n## Attachments")
        for a in attachments:
            md_parts.append(f"- {a}")

    full_md = "\n\n".join(md_parts)
    title = subject or file_path.stem

    return ParsedDocument(
        title=title,
        source_path=str(file_path),
        source_format="eml",
        total_pages=1,
        toc=_extract_toc_from_markdown(full_md),
        pages=[PageContent(page_num=1, markdown=full_md)],
    )


def _parse_msg(file_path: Path) -> ParsedDocument:
    """Parse an Outlook MSG file."""
    try:
        import extract_msg
    except ImportError:
        raise ImportError("MSG parsing requires extract-msg. Install with: pip install extract-msg")

    msg = extract_msg.Message(str(file_path))
    md_parts: list[str] = []

    md_parts.append(f"# {msg.subject or 'Untitled Email'}")
    md_parts.append(f"**From:** {msg.sender}")
    md_parts.append(f"**To:** {msg.to}")
    if msg.date:
        md_parts.append(f"**Date:** {msg.date}")
    md_parts.append("---")

    if msg.body:
        md_parts.append(msg.body.strip())

    if msg.attachments:
        md_parts.append("\n## Attachments")
        for a in msg.attachments:
            md_parts.append(f"- {a.longFilename or a.shortFilename or 'unnamed'}")

    msg.close()

    full_md = "\n\n".join(md_parts)
    title = msg.subject or file_path.stem

    return ParsedDocument(
        title=title,
        source_path=str(file_path),
        source_format="msg",
        total_pages=1,
        toc=_extract_toc_from_markdown(full_md),
        pages=[PageContent(page_num=1, markdown=full_md)],
    )


# ---------------------------------------------------------------------------
# XML & JSON parsers
# ---------------------------------------------------------------------------


def _parse_xml(file_path: Path) -> ParsedDocument:
    """Parse an XML file. Converts to a readable markdown representation."""
    import xml.etree.ElementTree as ET

    text = file_path.read_text(errors="replace")
    if not text.strip():
        return ParsedDocument(
            title=file_path.stem,
            source_path=str(file_path),
            source_format="xml",
            pages=[],
        )

    try:
        root = ET.fromstring(text)
        md = _xml_to_markdown(root)
    except ET.ParseError:
        # Fallback: treat as plain text
        md = f"```xml\n{text[:10000]}\n```"

    title = file_path.stem.replace("_", " ").replace("-", " ").title()
    page = PageContent(page_num=1, markdown=md, has_code_blocks="```" in md)

    return ParsedDocument(
        title=title,
        source_path=str(file_path),
        source_format="xml",
        total_pages=1,
        pages=[page],
    )


def _xml_to_markdown(element, depth: int = 0) -> str:
    """Convert an XML element tree to markdown headings + content."""
    parts: list[str] = []
    tag = element.tag.split("}")[-1] if "}" in element.tag else element.tag  # strip namespace

    # Element with text content
    text = (element.text or "").strip()
    children = list(element)

    if children:
        # Container element → heading
        level = min(depth + 1, 6)
        parts.append(f"{'#' * level} {tag}")
        if text:
            parts.append(text)
        for child in children:
            parts.append(_xml_to_markdown(child, depth + 1))
    elif text:
        # Leaf element → key-value
        parts.append(f"**{tag}:** {text}")
    # Skip empty leaf elements

    # Attributes
    if element.attrib:
        attrs = ", ".join(f"{k}={v}" for k, v in element.attrib.items())
        parts.append(f"*({attrs})*")

    return "\n\n".join(parts)


def _parse_json(file_path: Path) -> ParsedDocument:
    """Parse a JSON or JSONL file into readable markdown."""
    import json

    text = file_path.read_text(errors="replace").strip()
    if not text:
        return ParsedDocument(
            title=file_path.stem,
            source_path=str(file_path),
            source_format="json",
            pages=[],
        )

    ext = file_path.suffix.lower()
    md_parts: list[str] = []

    if ext == ".jsonl":
        # JSONL: each line is a separate JSON object
        for i, line in enumerate(text.split("\n")):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                md_parts.append(f"## Record {i + 1}")
                md_parts.append(_json_to_markdown(obj))
            except json.JSONDecodeError:
                md_parts.append(f"```\n{line}\n```")
    else:
        try:
            data = json.loads(text)
            md_parts.append(_json_to_markdown(data))
        except json.JSONDecodeError:
            md_parts.append(f"```json\n{text[:10000]}\n```")

    full_md = "\n\n".join(md_parts)
    title = file_path.stem.replace("_", " ").replace("-", " ").title()

    # Split large JSON into pages (~50 records per page for JSONL)
    pages = [PageContent(page_num=1, markdown=full_md)]

    return ParsedDocument(
        title=title,
        source_path=str(file_path),
        source_format="json",
        total_pages=1,
        pages=pages,
    )


def _json_to_markdown(data, depth: int = 0) -> str:
    """Convert a JSON value to readable markdown."""
    if isinstance(data, dict):
        parts: list[str] = []
        for key, value in data.items():
            if isinstance(value, (dict, list)):
                level = min(depth + 2, 6)
                parts.append(f"{'#' * level} {key}")
                parts.append(_json_to_markdown(value, depth + 1))
            else:
                parts.append(f"**{key}:** {value}")
        return "\n\n".join(parts)
    elif isinstance(data, list):
        if not data:
            return "*empty list*"
        # If list of simple values, render as bullet list
        if all(isinstance(item, (str, int, float, bool)) for item in data):
            return "\n".join(f"- {item}" for item in data)
        # List of objects: render each
        parts = []
        for i, item in enumerate(data):
            parts.append(f"### Item {i + 1}")
            parts.append(_json_to_markdown(item, depth + 1))
        return "\n\n".join(parts)
    else:
        return str(data)


# ---------------------------------------------------------------------------
# Audio & Video parsers
# ---------------------------------------------------------------------------


def _format_timestamp(seconds: float) -> str:
    """Format seconds as [HH:MM:SS] or [MM:SS]."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h > 0:
        return f"[{h:02d}:{m:02d}:{s:02d}]"
    return f"[{m:02d}:{s:02d}]"


def _get_whisper_model() -> str:
    """Get the configured Whisper model name."""
    import os

    return os.environ.get("INGEST_WHISPER_MODEL", "base")


def _transcribe_audio(audio_path: Path) -> list[dict]:
    """Transcribe audio using faster-whisper. Returns list of segment dicts.

    Each segment: {"start": float, "end": float, "text": str}
    Requires: pip install ingestible[audio]
    """
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise ImportError(
            "Audio transcription requires faster-whisper. "
            "Install with: pip install ingestible[audio]"
        )

    model_name = _get_whisper_model()
    logger.info("Loading Whisper model '%s'...", model_name)
    model = WhisperModel(model_name, compute_type="auto")

    logger.info("Transcribing %s...", audio_path.name)
    segments_iter, info = model.transcribe(str(audio_path), beam_size=5)

    logger.info(
        "Detected language: %s (probability %.2f), duration: %.0fs",
        info.language,
        info.language_probability,
        info.duration,
    )

    segments = []
    for seg in segments_iter:
        text = seg.text.strip()
        if text:
            segments.append({"start": seg.start, "end": seg.end, "text": text})

    return segments


def _segments_to_pages(segments: list[dict], page_duration: float = 120.0) -> list[PageContent]:
    """Group transcription segments into pages by time windows.

    Each page covers ~page_duration seconds. Segments are grouped by time,
    with timestamps rendered as markdown markers.
    """
    if not segments:
        return []

    pages: list[PageContent] = []
    current_parts: list[str] = []
    page_start = segments[0]["start"]
    page_end = segments[0]["end"]
    page_num = 1

    for seg in segments:
        # Start a new page if we've exceeded the duration
        if seg["start"] - page_start >= page_duration and current_parts:
            md = "\n\n".join(current_parts)
            pages.append(
                PageContent(
                    page_num=page_num,
                    markdown=md,
                    timestamp_start=page_start,
                    timestamp_end=page_end,
                )
            )
            page_num += 1
            current_parts = []
            page_start = seg["start"]

        ts = _format_timestamp(seg["start"])
        current_parts.append(f"{ts} {seg['text']}")
        page_end = seg["end"]

    # Flush remaining segments
    if current_parts:
        md = "\n\n".join(current_parts)
        pages.append(
            PageContent(
                page_num=page_num,
                markdown=md,
                timestamp_start=page_start,
                timestamp_end=page_end,
            )
        )

    return pages


def _parse_audio(file_path: Path) -> ParsedDocument:
    """Parse an audio file via ASR transcription (faster-whisper).

    Transcribes audio → timestamped text → groups into pages by time windows.
    """
    segments = _transcribe_audio(file_path)

    if not segments:
        return ParsedDocument(
            title=file_path.stem,
            source_path=str(file_path),
            source_format="audio",
            pages=[],
        )

    pages = _segments_to_pages(segments)
    full_md = "\n\n".join(p.markdown for p in pages)
    toc = _extract_toc_from_markdown(full_md)
    title = file_path.stem.replace("_", " ").replace("-", " ").title()

    duration = segments[-1]["end"] if segments else 0
    total_minutes = int(duration / 60)

    logger.info(
        "Transcribed %s: %d segments, %d pages, %d min",
        file_path.name,
        len(segments),
        len(pages),
        total_minutes,
    )

    return ParsedDocument(
        title=title,
        source_path=str(file_path),
        source_format="audio",
        total_pages=len(pages),
        toc=toc,
        pages=pages,
    )


def _extract_audio_from_video(video_path: Path) -> Path:
    """Extract audio track from video using ffmpeg. Returns temp .wav path."""
    import subprocess
    import tempfile

    audio_path = Path(tempfile.mktemp(suffix=".wav"))

    result = subprocess.run(
        [
            "ffmpeg",
            "-i",
            str(video_path),
            "-vn",  # no video
            "-acodec",
            "pcm_s16le",  # WAV PCM
            "-ar",
            "16000",  # 16kHz (Whisper optimal)
            "-ac",
            "1",  # mono
            "-y",  # overwrite
            str(audio_path),
        ],
        capture_output=True,
        text=True,
        timeout=600,  # 10 min max
    )

    if result.returncode != 0:
        audio_path.unlink(missing_ok=True)
        raise RuntimeError(f"ffmpeg audio extraction failed: {result.stderr[:500]}")

    return audio_path


def _extract_keyframes(
    video_path: Path, doc_dir: Path | None = None, interval: int = 60
) -> list[FigureRef]:
    """Extract keyframes from video at regular intervals using ffmpeg.

    Returns FigureRef list. Images saved to doc_dir/figures/ if provided.
    """
    import subprocess

    if doc_dir is None:
        return []

    figures_dir = doc_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    # Get video duration
    try:
        probe = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(video_path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        duration = float(probe.stdout.strip())
    except (subprocess.TimeoutExpired, ValueError):
        logger.warning("Could not determine video duration, skipping keyframe extraction")
        return []

    figures: list[FigureRef] = []
    timestamps = list(range(0, int(duration), interval))
    if not timestamps:
        timestamps = [0]

    for i, ts in enumerate(timestamps):
        fig_id = f"keyframe-{i + 1}"
        filename = f"{fig_id}.jpg"
        output_path = figures_dir / filename

        try:
            subprocess.run(
                [
                    "ffmpeg",
                    "-ss",
                    str(ts),
                    "-i",
                    str(video_path),
                    "-vframes",
                    "1",
                    "-q:v",
                    "2",
                    "-y",
                    str(output_path),
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if output_path.exists() and output_path.stat().st_size > 0:
                figures.append(
                    FigureRef(
                        figure_id=fig_id,
                        filename=filename,
                        caption=f"Keyframe at {_format_timestamp(ts)}",
                        page_num=None,
                    )
                )
        except subprocess.TimeoutExpired:
            logger.warning("Keyframe extraction timed out at %ds", ts)
            continue

    logger.info("Extracted %d keyframes from %s", len(figures), video_path.name)
    return figures


def _parse_video(file_path: Path) -> ParsedDocument:
    """Parse a video file: extract audio → transcribe → timestamped text.

    Also extracts keyframes at 60-second intervals as figures.
    Requires: pip install ingestible[audio] + ffmpeg on PATH
    """
    import shutil

    if not shutil.which("ffmpeg"):
        raise RuntimeError(
            "Video parsing requires ffmpeg on PATH. "
            "Install via: brew install ffmpeg (macOS) or apt install ffmpeg (Linux)"
        )

    # Extract audio track
    logger.info("Extracting audio from %s...", file_path.name)
    audio_path = _extract_audio_from_video(file_path)

    try:
        segments = _transcribe_audio(audio_path)
    finally:
        audio_path.unlink(missing_ok=True)

    if not segments:
        return ParsedDocument(
            title=file_path.stem,
            source_path=str(file_path),
            source_format="video",
            pages=[],
        )

    pages = _segments_to_pages(segments)
    full_md = "\n\n".join(p.markdown for p in pages)
    toc = _extract_toc_from_markdown(full_md)
    title = file_path.stem.replace("_", " ").replace("-", " ").title()

    # Keyframe extraction happens later in the orchestrator (needs doc_dir)
    # We store the video path so the orchestrator can call _extract_keyframes

    duration = segments[-1]["end"] if segments else 0
    total_minutes = int(duration / 60)

    logger.info(
        "Transcribed video %s: %d segments, %d pages, %d min",
        file_path.name,
        len(segments),
        len(pages),
        total_minutes,
    )

    return ParsedDocument(
        title=title,
        source_path=str(file_path),
        source_format="video",
        total_pages=len(pages),
        toc=toc,
        pages=pages,
    )


# ---------------------------------------------------------------------------
# ZIP archive parsers (Notion / Confluence exports)
# ---------------------------------------------------------------------------


def _parse_zip_archive(file_path: Path) -> ParsedDocument:
    """Parse a ZIP archive — auto-detects Notion or Confluence export format."""
    import zipfile

    if not zipfile.is_zipfile(file_path):
        raise ValueError(f"Not a valid ZIP file: {file_path}")

    with zipfile.ZipFile(file_path, "r") as zf:
        names = zf.namelist()

        # Detect Confluence: has index.html at root
        if "index.html" in names or any(n.endswith("/index.html") for n in names):
            return _parse_confluence_zip(file_path, zf)

        # Detect Notion: has .md files with UUIDs in names
        md_files = [n for n in names if n.endswith(".md")]
        if md_files:
            return _parse_notion_zip(file_path, zf)

        # Generic ZIP: try to extract and parse individual supported files
        return _parse_generic_zip(file_path, zf)


def _parse_notion_zip(file_path: Path, zf) -> ParsedDocument:
    """Parse a Notion export ZIP. Each .md file becomes a page."""

    pages: list[PageContent] = []
    md_parts: list[str] = []

    # Sort by path depth then name for consistent ordering
    md_files = sorted(
        [n for n in zf.namelist() if n.endswith(".md") and not n.startswith("__MACOSX")],
        key=lambda n: (n.count("/"), n),
    )

    for page_num, name in enumerate(md_files, 1):
        content = zf.read(name).decode("utf-8", errors="replace").strip()
        if not content:
            continue

        # Clean Notion UUID from filename for display
        # Notion exports: "Page Title abc123def456.md"
        clean_name = Path(name).stem
        clean_name = re.sub(r"\s+[0-9a-f]{32}$", "", clean_name)

        # Add a heading if the file doesn't start with one
        if not content.startswith("#"):
            content = f"# {clean_name}\n\n{content}"

        # Clean up Notion-specific link syntax: [text](Page%20Name%20uuid.md) → [text]
        content = re.sub(r"\[([^\]]+)\]\([^)]*\.md\)", r"[\1]", content)

        pages.append(
            PageContent(page_num=page_num, markdown=content, has_code_blocks="```" in content)
        )
        md_parts.append(content)

    if not pages:
        return ParsedDocument(
            title=file_path.stem,
            source_path=str(file_path),
            source_format="notion",
            pages=[],
        )

    full_md = "\n\n".join(md_parts)
    toc = _extract_toc_from_markdown(full_md)
    title = _detect_title(full_md, file_path)

    return ParsedDocument(
        title=title,
        source_path=str(file_path),
        source_format="notion",
        total_pages=len(pages),
        toc=toc,
        pages=pages,
    )


def _parse_confluence_zip(file_path: Path, zf) -> ParsedDocument:
    """Parse a Confluence HTML export ZIP."""
    from markdownify import markdownify

    pages: list[PageContent] = []
    md_parts: list[str] = []

    # Find all HTML files (excluding assets)
    html_files = sorted(
        [
            n
            for n in zf.namelist()
            if n.endswith(".html")
            and not n.startswith("__MACOSX")
            and "styles/" not in n
            and "images/" not in n
            and "attachments/" not in n
        ]
    )

    for page_num, name in enumerate(html_files, 1):
        html = zf.read(name).decode("utf-8", errors="replace")
        if not html.strip():
            continue

        # Strip scripts and styles
        html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)

        # Convert to markdown
        md = markdownify(html, heading_style="ATX").strip()
        if not md:
            continue

        pages.append(PageContent(page_num=page_num, markdown=md, has_code_blocks="```" in md))
        md_parts.append(md)

    if not pages:
        return ParsedDocument(
            title=file_path.stem,
            source_path=str(file_path),
            source_format="confluence",
            pages=[],
        )

    full_md = "\n\n".join(md_parts)
    toc = _extract_toc_from_markdown(full_md)
    title = _detect_title(full_md, file_path)

    return ParsedDocument(
        title=title,
        source_path=str(file_path),
        source_format="confluence",
        total_pages=len(pages),
        toc=toc,
        pages=pages,
    )


def _parse_generic_zip(file_path: Path, zf) -> ParsedDocument:
    """Parse a generic ZIP by extracting and concatenating supported text files."""
    pages: list[PageContent] = []
    md_parts: list[str] = []

    text_exts = {".md", ".txt", ".html", ".htm", ".rst", ".adoc", ".csv", ".json", ".xml"}

    for name in sorted(zf.namelist()):
        ext = Path(name).suffix.lower()
        if ext not in text_exts or name.startswith("__MACOSX"):
            continue
        try:
            content = zf.read(name).decode("utf-8", errors="replace").strip()
        except Exception:
            continue
        if not content:
            continue

        if ext in (".html", ".htm"):
            try:
                from markdownify import markdownify

                content = markdownify(content, heading_style="ATX").strip()
            except Exception:
                pass

        page_num = len(pages) + 1
        pages.append(PageContent(page_num=page_num, markdown=content))
        md_parts.append(content)

    if not pages:
        return ParsedDocument(
            title=file_path.stem,
            source_path=str(file_path),
            source_format="zip",
            pages=[],
        )

    full_md = "\n\n".join(md_parts)
    toc = _extract_toc_from_markdown(full_md)
    title = _detect_title(full_md, file_path)

    return ParsedDocument(
        title=title,
        source_path=str(file_path),
        source_format="zip",
        total_pages=len(pages),
        toc=toc,
        pages=pages,
    )
