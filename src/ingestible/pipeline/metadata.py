"""Document metadata extraction — per-format extractors for file-level properties."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from ingestible.models.metadata import DocumentMetadata

logger = logging.getLogger(__name__)


def extract_metadata(file_path: Path) -> DocumentMetadata:
    """Extract metadata from a document file. Dispatches by extension."""
    ext = file_path.suffix.lower()
    try:
        if ext == ".pdf":
            return _extract_pdf(file_path)
        elif ext == ".docx":
            return _extract_docx(file_path)
        elif ext in (".html", ".htm"):
            return _extract_html(file_path)
        else:
            return _extract_text(file_path)
    except Exception as e:
        logger.warning("Metadata extraction failed for %s: %s", file_path.name, e)
        return DocumentMetadata()


def _extract_pdf(file_path: Path) -> DocumentMetadata:
    """Extract metadata from PDF using pymupdf."""
    import pymupdf

    doc = pymupdf.open(str(file_path))
    meta = doc.metadata or {}

    keywords_raw = meta.get("keywords", "") or ""
    keywords = [k.strip() for k in re.split(r"[,;]", keywords_raw) if k.strip()]

    creation_date = _parse_pdf_date(meta.get("creationDate", ""))
    mod_date = _parse_pdf_date(meta.get("modDate", ""))

    # Word count from text
    word_count = 0
    for page in doc:
        text = page.get_text()
        word_count += len(text.split())

    result = DocumentMetadata(
        author=meta.get("author", "") or "",
        creator=meta.get("creator", "") or "",
        producer=meta.get("producer", "") or "",
        subject=meta.get("subject", "") or "",
        keywords=keywords,
        creation_date=creation_date,
        modification_date=mod_date,
        page_count=len(doc),
        word_count=word_count,
    )
    doc.close()
    return result


def _parse_pdf_date(date_str: str) -> str:
    """Parse PDF date format (D:YYYYMMDDHHmmSS) to ISO-ish string."""
    if not date_str:
        return ""
    # Strip D: prefix and timezone suffix
    date_str = date_str.replace("D:", "").strip()
    # Take just the date/time portion
    match = re.match(r"(\d{4})(\d{2})?(\d{2})?(\d{2})?(\d{2})?(\d{2})?", date_str)
    if not match:
        return date_str
    parts = [g for g in match.groups() if g]
    if len(parts) >= 3:
        date_part = f"{parts[0]}-{parts[1]}-{parts[2]}"
        if len(parts) >= 6:
            return f"{date_part}T{parts[3]}:{parts[4]}:{parts[5]}"
        return date_part
    return date_str


def _extract_docx(file_path: Path) -> DocumentMetadata:
    """Extract metadata from DOCX core properties."""
    from docx import Document as DocxDocument

    doc = DocxDocument(str(file_path))
    props = doc.core_properties

    keywords_raw = props.keywords or ""
    keywords = [k.strip() for k in re.split(r"[,;]", keywords_raw) if k.strip()]

    creation_date = ""
    if props.created:
        creation_date = props.created.isoformat()

    mod_date = ""
    if props.modified:
        mod_date = props.modified.isoformat()

    # Word count from paragraphs
    word_count = sum(len(p.text.split()) for p in doc.paragraphs)

    return DocumentMetadata(
        author=props.author or "",
        subject=props.subject or "",
        keywords=keywords,
        creation_date=creation_date,
        modification_date=mod_date,
        language=props.language or "",
        word_count=word_count,
    )


def _extract_html(file_path: Path) -> DocumentMetadata:
    """Extract metadata from HTML meta tags."""
    text = file_path.read_text(errors="replace")

    def _meta(name: str) -> str:
        m = re.search(
            rf'<meta\s+(?:name|property)=["\'](?:{name})["\']\s+content=["\']([^"\']*)["\']',
            text,
            re.IGNORECASE,
        )
        return m.group(1).strip() if m else ""

    keywords_raw = _meta("keywords")
    keywords = [k.strip() for k in re.split(r"[,;]", keywords_raw) if k.strip()]

    lang = ""
    lang_match = re.search(r'<html[^>]*\slang=["\']([^"\']+)["\']', text, re.IGNORECASE)
    if lang_match:
        lang = lang_match.group(1)

    word_count = len(re.sub(r"<[^>]+>", " ", text).split())

    return DocumentMetadata(
        author=_meta("author"),
        keywords=keywords,
        language=lang,
        word_count=word_count,
    )


def _extract_text(file_path: Path) -> DocumentMetadata:
    """Minimal metadata for plain text / markdown files."""
    text = file_path.read_text(errors="replace")
    return DocumentMetadata(
        word_count=len(text.split()),
    )
