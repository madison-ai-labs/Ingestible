"""Stage 1b — Preprocessing / Cleaning.

Normalises Unicode, collapses whitespace, strips repeated headers/footers
from multi-page PDFs, and removes empty heading-only sections.
"""

from __future__ import annotations

import logging
import re
import unicodedata

from ingestible.models.document import PageContent, ParsedDocument

logger = logging.getLogger(__name__)


def clean_document(doc: ParsedDocument) -> ParsedDocument:
    """Apply Unicode NFC, whitespace collapse, header/footer removal."""
    pages = doc.pages

    # Header/footer detection (PDFs with >2 pages only)
    headers: set[str] = set()
    footers: set[str] = set()
    if doc.source_format == "pdf" and len(pages) > 2:
        headers, footers = _detect_repeated_lines(pages, threshold=0.5)
        if headers or footers:
            logger.info(
                "Detected %d header(s) and %d footer(s) to strip",
                len(headers),
                len(footers),
            )
            pages = _strip_headers_footers(pages, headers, footers)

    # Per-page cleaning
    cleaned_pages: list[PageContent] = []
    for page in pages:
        md = page.markdown
        md = _normalize_unicode(md)
        md = _collapse_whitespace(md)
        md = _filter_empty_sections(md)
        cleaned_pages.append(page.model_copy(update={"markdown": md}))

    return doc.model_copy(update={"pages": cleaned_pages})


def _normalize_unicode(text: str) -> str:
    """Apply Unicode NFC normalisation."""
    return unicodedata.normalize("NFC", text)


def _collapse_whitespace(text: str) -> str:
    """Multi-space → single, \\r\\n → \\n, tabs → space, 3+ newlines → 2."""
    text = text.replace("\r\n", "\n")
    text = text.replace("\t", " ")
    text = re.sub(r"[^\S\n]+", " ", text)  # non-newline whitespace runs → single space
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _detect_repeated_lines(
    pages: list[PageContent], threshold: float = 0.5
) -> tuple[set[str], set[str]]:
    """Find lines that repeat as the first/last non-empty line on >threshold of pages.

    Skips pages with <50 chars (title pages, blanks).
    """
    first_lines: dict[str, int] = {}
    last_lines: dict[str, int] = {}
    eligible = 0

    for page in pages:
        text = page.markdown.strip()
        if len(text) < 50:
            continue
        eligible += 1

        lines = [line.strip() for line in text.split("\n") if line.strip()]
        if not lines:
            continue

        first = lines[0]
        first_lines[first] = first_lines.get(first, 0) + 1

        last = lines[-1]
        last_lines[last] = last_lines.get(last, 0) + 1

    if eligible < 3:
        return set(), set()

    min_count = eligible * threshold
    headers = {line for line, cnt in first_lines.items() if cnt >= min_count}
    footers = {line for line, cnt in last_lines.items() if cnt >= min_count}
    return headers, footers


def _strip_headers_footers(
    pages: list[PageContent],
    headers: set[str],
    footers: set[str],
) -> list[PageContent]:
    """Remove detected header/footer lines from each page."""
    cleaned: list[PageContent] = []
    for page in pages:
        lines = page.markdown.split("\n")
        out: list[str] = []
        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped:
                out.append(line)
                continue
            # Check if it's the first non-empty line and matches a header
            is_first_nonempty = all(not ln.strip() for ln in lines[:i])
            if is_first_nonempty and stripped in headers:
                continue
            # Check if it's the last non-empty line and matches a footer
            is_last_nonempty = all(not ln.strip() for ln in lines[i + 1 :])
            if is_last_nonempty and stripped in footers:
                continue
            out.append(line)
        cleaned.append(page.model_copy(update={"markdown": "\n".join(out)}))
    return cleaned


def _filter_empty_sections(text: str) -> str:
    """Remove heading-only sections (heading followed by another heading or end)."""
    lines = text.split("\n")
    result: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        # Is this a markdown heading?
        if re.match(r"^#{1,6}\s+", line):
            # Look ahead: skip blank lines, check if next content is another heading or EOF
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            if j >= len(lines) or re.match(r"^#{1,6}\s+", lines[j]):
                # Empty section — skip the heading (and blank lines after it)
                i = j
                continue
        result.append(line)
        i += 1
    return "\n".join(result)
