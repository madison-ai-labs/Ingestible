"""Stage 2 — Structure Detection.

Builds a hierarchy tree from the parsed document.
Strategy:
  1. Parse embedded TOC tables (with page numbers + indentation hints)
  2. Fall back to heading detection from markdown
  3. When all headings are flat (same level), infer hierarchy from page ranges
"""

from __future__ import annotations

import hashlib
import logging
import re

from ingestible.models.document import (
    DocumentStructure,
    ParsedDocument,
    StructureNode,
    TOCEntry,
)

logger = logging.getLogger(__name__)

SPECIAL_SECTIONS = {"index", "glossary", "bibliography", "appendix", "references"}

# Titles that are clearly top-level document sections
TOP_LEVEL_MARKERS = {
    "introduction",
    "conclusion",
    "appendix",
    "acknowledgements",
    "references",
    "endnotes",
    "bibliography",
}


def detect_structure(doc: ParsedDocument, doc_id: str) -> DocumentStructure:
    """Build a document hierarchy tree from a parsed document."""
    # Try to extract TOC with page numbers from embedded TOC tables first
    toc = _extract_toc_from_tables(doc.full_markdown)

    if not toc:
        toc = doc.toc or _detect_headings_from_markdown(doc.full_markdown)

    toc = _normalize_levels(toc)

    # If all entries are the same level and we have page numbers, infer hierarchy
    if toc and _is_flat(toc) and _has_page_numbers(toc):
        toc = _infer_hierarchy_from_pages(toc, doc.total_pages)

    if not toc:
        logger.info("No headings detected, treating entire document as single section")
        root = StructureNode(
            id=f"{doc_id}-root",
            title=doc.title,
            level=0,
            page_start=1,
            page_end=doc.total_pages,
            content=doc.full_markdown,
        )
        return DocumentStructure(doc_id=doc_id, title=doc.title, root=root)

    root = _build_tree(toc, doc, doc_id)
    _assign_content(root, doc)

    # Log tree summary
    ch_count = len(root.children)
    sec_count = sum(len(c.children) for c in root.children)
    logger.info("Structure detected: %d chapters, %d sections", ch_count, sec_count)

    return DocumentStructure(doc_id=doc_id, title=doc.title, root=root)


def _extract_toc_from_tables(md: str) -> list[TOCEntry]:
    """Extract TOC entries from markdown tables found in 'Table of contents' sections.

    These tables have rows like: | Section Title | 42 |
    """
    entries: list[TOCEntry] = []

    # Find all TOC sections
    toc_blocks = re.findall(
        r"##\s+Table of contents\s*\n(.*?)(?=\n## (?!Table)|$)",
        md,
        re.DOTALL,
    )

    for block in toc_blocks:
        # Parse table rows: | title | page_num |
        for m in re.finditer(r"\|\s*(.+?)\s*\|\s*(\d+)\s*\|", block):
            title = m.group(1).strip()
            page = int(m.group(2))
            # Skip separator rows like |---|---|
            if re.match(r"^[-|:\s]+$", title):
                continue
            if title:
                entries.append(TOCEntry(level=1, title=title, page=page))

    if entries:
        logger.info("Extracted %d TOC entries from embedded tables", len(entries))

    return entries


def _normalize_levels(toc: list[TOCEntry]) -> list[TOCEntry]:
    """Normalize heading levels so the minimum level becomes 1."""
    if not toc:
        return toc
    min_level = min(e.level for e in toc)
    if min_level <= 1:
        return toc
    offset = min_level - 1
    return [TOCEntry(level=e.level - offset, title=e.title, page=e.page) for e in toc]


def _is_flat(toc: list[TOCEntry]) -> bool:
    """Check if all TOC entries are at the same level."""
    levels = {e.level for e in toc}
    return len(levels) == 1


def _has_page_numbers(toc: list[TOCEntry]) -> bool:
    """Check if most TOC entries have page numbers."""
    with_pages = sum(1 for e in toc if e.page is not None)
    return with_pages > len(toc) * 0.5


def _infer_hierarchy_from_pages(toc: list[TOCEntry], total_pages: int) -> list[TOCEntry]:
    """Infer a hierarchy from a flat TOC using page ranges.

    A section that spans many pages and is followed by sections within
    that page range is likely a parent. Also uses title patterns
    (e.g., known top-level markers, "Risk"/"Mitigations" as sub-items).
    """
    if len(toc) < 3:
        return toc

    # Step 1: Compute page span for each entry
    pages = []
    for i, entry in enumerate(toc):
        start = entry.page or 0
        # End page = next entry's start page, or total_pages
        end = toc[i + 1].page if i + 1 < len(toc) and toc[i + 1].page else total_pages
        pages.append((start, end, end - start))

    # Step 2: Known sub-section titles (these are never top-level)
    sub_titles = {
        "risk",
        "mitigations",
        "example scenario:",
        "the attack",
        "the result",
        "the scenario: a corporate code repository",
    }

    # Step 3: Assign levels
    result = []
    for i, entry in enumerate(toc):
        span = pages[i][2]
        title_lower = entry.title.lower().strip()

        # Known top-level patterns
        is_top = (
            any(marker in title_lower for marker in TOP_LEVEL_MARKERS)
            or ":" in entry.title  # "Introduction: Models, Tools and Agents"
        )
        # Known sub-section patterns
        is_sub = title_lower in sub_titles

        if is_sub:
            level = 3
        elif is_top or span >= 5:
            # Sections spanning 5+ pages are likely top-level chapters
            level = 1
        elif span >= 2:
            level = 2
        else:
            level = 3

        result.append(TOCEntry(level=level, title=entry.title, page=entry.page))

    # Step 4: Fix orphan level-3s that have no level-2 parent
    # If a level 3 directly follows a level 1, bump it to level 2
    fixed = []
    for i, entry in enumerate(result):
        if entry.level == 3:
            # Find nearest preceding non-3
            parent_level = 1
            for j in range(i - 1, -1, -1):
                if result[j].level < 3:
                    parent_level = result[j].level
                    break
            if parent_level == 1:
                fixed.append(TOCEntry(level=2, title=entry.title, page=entry.page))
                continue
        fixed.append(entry)

    # Log the inferred hierarchy
    level_counts = {}
    for e in fixed:
        level_counts[e.level] = level_counts.get(e.level, 0) + 1
    logger.info("Inferred hierarchy: %s", level_counts)

    return fixed


def _detect_headings_from_markdown(md: str) -> list[TOCEntry]:
    """Detect headings from markdown heading syntax and numbering patterns."""
    entries = []
    for line in md.split("\n"):
        m = re.match(r"^(#{1,6})\s+(.+)$", line)
        if m:
            entries.append(TOCEntry(level=len(m.group(1)), title=m.group(2).strip()))
            continue

        m = re.match(r"^(?:Chapter|Part)\s+(\d+)[:\s]+(.+)$", line, re.IGNORECASE)
        if m:
            entries.append(TOCEntry(level=1, title=line.strip()))
            continue

        m = re.match(r"^(\d+(?:\.\d+)*)\s+(.+)$", line)
        if m:
            dots = m.group(1).count(".")
            entries.append(TOCEntry(level=dots + 1, title=line.strip()))

    return entries


def _make_node_id(doc_id: str, title: str, level: int) -> str:
    h = hashlib.md5(f"{title}:{level}".encode(), usedforsecurity=False).hexdigest()[:8]
    return f"{doc_id}-L{level}-{h}"


def _is_special(title: str) -> bool:
    lower = title.lower().strip()
    return any(s in lower for s in SPECIAL_SECTIONS)


def _build_tree(toc: list[TOCEntry], doc: ParsedDocument, doc_id: str) -> StructureNode:
    """Build a tree from a flat list of TOC entries."""
    root = StructureNode(
        id=f"{doc_id}-root",
        title=doc.title,
        level=0,
        page_start=1,
        page_end=doc.total_pages,
    )

    stack: list[StructureNode] = [root]

    for entry in toc:
        node = StructureNode(
            id=_make_node_id(doc_id, entry.title, entry.level),
            title=entry.title,
            level=entry.level,
            page_start=entry.page,
            is_special=_is_special(entry.title),
        )

        while len(stack) > 1 and stack[-1].level >= entry.level:
            stack.pop()

        stack[-1].children.append(node)
        stack.append(node)

    _propagate_page_ranges(root, doc.total_pages)
    return root


def _propagate_page_ranges(node: StructureNode, doc_total_pages: int) -> None:
    children = node.children
    for i, child in enumerate(children):
        if child.page_end is None:
            if i + 1 < len(children) and children[i + 1].page_start is not None:
                child.page_end = children[i + 1].page_start
            else:
                child.page_end = node.page_end or doc_total_pages
        _propagate_page_ranges(child, doc_total_pages)


def _assign_content(root: StructureNode, doc: ParsedDocument) -> None:
    """Assign content to structure nodes by splitting markdown on heading boundaries."""
    full_md = doc.full_markdown
    sections = _split_md_by_headings(full_md)

    # Build title→node lookup for all nodes
    all_nodes = list(root.walk())
    title_to_node: dict[str, StructureNode] = {}
    for node in all_nodes:
        if node.level > 0:
            title_to_node[node.title.strip().lower()] = node

    unmatched: list[str] = []
    for heading_title, body in sections:
        key = heading_title.strip().lower()
        node = title_to_node.get(key)
        if node is not None:
            node.content = body.strip()
        else:
            unmatched.append(body)

    if unmatched:
        root.content = "\n\n".join(unmatched)


def _split_md_by_headings(md: str) -> list[tuple[str, str]]:
    """Split markdown into (heading_title, body_text) pairs."""
    pattern = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
    matches = list(pattern.finditer(md))

    if not matches:
        return [("", md)]

    sections: list[tuple[str, str]] = []

    if matches[0].start() > 0:
        preamble = md[: matches[0].start()]
        if preamble.strip():
            sections.append(("", preamble))

    for i, m in enumerate(matches):
        title = m.group(2).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(md)
        body = md[start:end]
        sections.append((title, body))

    return sections
