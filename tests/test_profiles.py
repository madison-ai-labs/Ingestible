"""Tests for extraction profiles — auto-detection, profile registry, and citation round-trip."""

from __future__ import annotations

import json
from pathlib import Path

from ingestible.config import Settings
from ingestible.models.chunks import (
    ChunkPosition,
    ChunkSet,
    L0Chunk,
    L1Chunk,
    L2Chunk,
    L3Chunk,
)
from ingestible.models.document import (
    DocumentStructure,
    PageContent,
    ParsedDocument,
    StructureNode,
    TOCEntry,
)
from ingestible.models.enrichment import Citation
from ingestible.pipeline.stage6_storage import load_chunks, save_document
from ingestible.profiles import PROFILES, ExtractionProfile, detect_profile


# ---------------------------------------------------------------------------
# Profile registry
# ---------------------------------------------------------------------------


def test_all_profiles_present():
    assert set(PROFILES) == {"paper", "article", "documentation", "general"}


def test_profile_types():
    for name, profile in PROFILES.items():
        assert isinstance(profile, ExtractionProfile)
        assert profile.name == name


def test_paper_profile_enables_citations():
    assert PROFILES["paper"].extract_citations is True
    assert PROFILES["paper"].extract_methodology is True


def test_non_paper_profiles_disable_citations():
    for name in ("article", "documentation", "general"):
        assert PROFILES[name].extract_citations is False


# ---------------------------------------------------------------------------
# Auto-detection heuristics
# ---------------------------------------------------------------------------


def _make_parsed(markdown: str, toc: list[TOCEntry] | None = None, fmt: str = ".pdf") -> ParsedDocument:
    return ParsedDocument(
        title="Test",
        source_path="/test" + fmt,
        source_format=fmt,
        total_pages=1,
        toc=toc or [],
        pages=[PageContent(page_num=1, markdown=markdown)],
    )


def test_detect_paper_from_headings():
    md = """# Abstract
Some abstract text.

# Introduction
Intro text.

# Methods
Methodology details.

# Results
Results here.

# Discussion
Discussion here.

# References
[1] Smith et al. 2024.
"""
    doc = _make_parsed(md)
    assert detect_profile(doc) == "paper"


def test_detect_paper_from_toc():
    toc = [
        TOCEntry(level=1, title="Abstract", page=1),
        TOCEntry(level=1, title="Introduction", page=2),
        TOCEntry(level=1, title="Methodology", page=5),
        TOCEntry(level=1, title="Results", page=10),
        TOCEntry(level=1, title="Discussion", page=15),
        TOCEntry(level=1, title="References", page=20),
    ]
    doc = _make_parsed("Minimal content", toc=toc)
    assert detect_profile(doc) == "paper"


def test_detect_documentation_from_headings():
    md = """# Getting Started

## Installation
```bash
pip install mylib
```

## Configuration
Set the `API_KEY` environment variable.

## API Reference
```python
def hello(): ...
```

## Usage
Example usage here.
"""
    doc = _make_parsed(md, fmt=".md")
    assert detect_profile(doc) == "documentation"


def test_detect_documentation_from_code_blocks():
    md = "# Guide\n\n" + "```python\ncode()\n```\n\n" * 5
    doc = _make_parsed(md, fmt=".md")
    assert detect_profile(doc) == "documentation"


def test_detect_documentation_from_rst_format():
    md = """Guide
=====

Installation
------------

```bash
pip install mylib
```

```python
import mylib
```
"""
    doc = _make_parsed(md, fmt=".rst")
    assert detect_profile(doc) == "documentation"


def test_detect_article_from_html():
    md = "The economy showed signs of recovery this quarter, analysts say."
    doc = _make_parsed(md, fmt=".html")
    assert detect_profile(doc) == "article"


def test_detect_general_fallback():
    md = "Some random content about various topics."
    doc = _make_parsed(md, fmt=".pdf")
    assert detect_profile(doc) == "general"


def test_detect_article_for_plain_markdown():
    md = "An opinion piece about technology trends and their impact on society."
    doc = _make_parsed(md, fmt=".md")
    assert detect_profile(doc) == "article"


# ---------------------------------------------------------------------------
# Citation round-trip (save → load)
# ---------------------------------------------------------------------------


def _make_chunks_with_citations() -> tuple[DocumentStructure, ChunkSet]:
    structure = DocumentStructure(
        doc_id="cite-doc",
        title="Citation Test",
        root=StructureNode(id="root", title="Citation Test", level=0),
    )
    citations = [
        Citation(
            citation_id="[1]",
            authors=["Smith, J.", "Doe, A."],
            title="A Great Paper",
            year="2024",
            venue="Nature",
            doi="10.1234/test",
            raw_text="[1] Smith, J., Doe, A. A Great Paper. Nature, 2024.",
            inline_references=["p1", "p2"],
        ),
        Citation(
            citation_id="[2]",
            authors=["Jones, B."],
            title="Another Paper",
            year="2023",
            venue="Science",
            raw_text="[2] Jones, B. Another Paper. Science, 2023.",
        ),
    ]
    chunks = ChunkSet(
        doc_id="cite-doc",
        l0=L0Chunk(
            chunk_id="cite-doc-L0",
            title="Citation Test",
            executive_summary="A test document for citation extraction.",
            key_findings=["Finding 1", "Finding 2"],
            methodology="Mixed methods",
            limitations="Small sample",
            document_type="paper",
            target_audience="Researchers",
        ),
        l1_chunks=[
            L1Chunk(chunk_id="ch1", title="Chapter 1", content="Chapter content"),
        ],
        l2_chunks=[
            L2Chunk(
                chunk_id="sec1",
                title="Section 1",
                content="Section content",
                parent_chapter_id="ch1",
            ),
        ],
        l3_chunks=[
            L3Chunk(
                chunk_id="p1",
                content="As shown by Smith [1]...",
                parent_section_id="sec1",
                position=ChunkPosition(chapter="ch1", section="sec1", index=0),
                cited_references=["[1]"],
            ),
            L3Chunk(
                chunk_id="p2",
                content="Jones [2] found...",
                parent_section_id="sec1",
                position=ChunkPosition(chapter="ch1", section="sec1", index=1),
                cited_references=["[1]", "[2]"],
            ),
        ],
        citations=citations,
    )
    return structure, chunks


def test_citation_roundtrip(tmp_path):
    """Citations survive save -> load."""
    settings = Settings(data_dir=tmp_path)
    structure, chunks = _make_chunks_with_citations()

    save_document(structure, chunks, settings, extraction_profile="paper")
    loaded = load_chunks(settings.documents_dir / "cite-doc")

    assert len(loaded.citations) == 2

    c1 = loaded.citations[0]
    assert c1.citation_id == "[1]"
    assert c1.authors == ["Smith, J.", "Doe, A."]
    assert c1.title == "A Great Paper"
    assert c1.year == "2024"
    assert c1.venue == "Nature"
    assert c1.doi == "10.1234/test"
    assert c1.inline_references == ["p1", "p2"]

    c2 = loaded.citations[1]
    assert c2.citation_id == "[2]"
    assert c2.authors == ["Jones, B."]


def test_citation_file_created(tmp_path):
    """citations.json is written when citations exist."""
    settings = Settings(data_dir=tmp_path)
    structure, chunks = _make_chunks_with_citations()
    save_document(structure, chunks, settings)

    doc_dir = settings.documents_dir / "cite-doc"
    assert (doc_dir / "citations.json").exists()

    data = json.loads((doc_dir / "citations.json").read_text())
    assert len(data["citations"]) == 2


def test_no_citation_file_when_empty(tmp_path):
    """citations.json is NOT written when there are no citations."""
    settings = Settings(data_dir=tmp_path)
    structure = DocumentStructure(
        doc_id="no-cite",
        title="No Citations",
        root=StructureNode(id="root", title="No Citations", level=0),
    )
    chunks = ChunkSet(
        doc_id="no-cite",
        l0=L0Chunk(chunk_id="no-cite-L0", title="No Citations"),
    )
    save_document(structure, chunks, settings)

    doc_dir = settings.documents_dir / "no-cite"
    assert not (doc_dir / "citations.json").exists()


def test_load_chunks_without_citations(tmp_path):
    """load_chunks works for documents stored before citations existed."""
    settings = Settings(data_dir=tmp_path)
    structure = DocumentStructure(
        doc_id="old-doc",
        title="Old Doc",
        root=StructureNode(id="root", title="Old Doc", level=0),
    )
    chunks = ChunkSet(
        doc_id="old-doc",
        l0=L0Chunk(chunk_id="old-doc-L0", title="Old Doc"),
    )
    save_document(structure, chunks, settings)

    loaded = load_chunks(settings.documents_dir / "old-doc")
    assert loaded.citations == []


# ---------------------------------------------------------------------------
# L0 digest round-trip
# ---------------------------------------------------------------------------


def test_l0_digest_roundtrip(tmp_path):
    """All L0 digest fields survive save -> load."""
    settings = Settings(data_dir=tmp_path)
    structure, chunks = _make_chunks_with_citations()

    save_document(structure, chunks, settings, extraction_profile="paper")
    loaded = load_chunks(settings.documents_dir / "cite-doc")

    assert loaded.l0.executive_summary == "A test document for citation extraction."
    assert loaded.l0.key_findings == ["Finding 1", "Finding 2"]
    assert loaded.l0.methodology == "Mixed methods"
    assert loaded.l0.limitations == "Small sample"
    assert loaded.l0.document_type == "paper"
    assert loaded.l0.target_audience == "Researchers"


def test_l0_digest_defaults():
    """L0 digest fields default to empty when not set."""
    l0 = L0Chunk(chunk_id="test-L0", title="Test")
    assert l0.executive_summary == ""
    assert l0.key_findings == []
    assert l0.methodology == ""
    assert l0.limitations == ""
    assert l0.document_type == ""
    assert l0.target_audience == ""


# ---------------------------------------------------------------------------
# L3 cited_references round-trip
# ---------------------------------------------------------------------------


def test_l3_cited_references_roundtrip(tmp_path):
    """L3 cited_references survive save -> load."""
    settings = Settings(data_dir=tmp_path)
    structure, chunks = _make_chunks_with_citations()

    save_document(structure, chunks, settings)
    loaded = load_chunks(settings.documents_dir / "cite-doc")

    assert loaded.l3_chunks[0].cited_references == ["[1]"]
    assert loaded.l3_chunks[1].cited_references == ["[1]", "[2]"]


# ---------------------------------------------------------------------------
# Profile stored in meta.json
# ---------------------------------------------------------------------------


def test_profile_stored_in_meta(tmp_path):
    """extraction_profile is persisted in meta.json."""
    settings = Settings(data_dir=tmp_path)
    structure, chunks = _make_chunks_with_citations()

    save_document(structure, chunks, settings, extraction_profile="paper")

    meta_path = settings.documents_dir / "cite-doc" / "meta.json"
    meta = json.loads(meta_path.read_text())
    assert meta["extraction_profile"] == "paper"


# ---------------------------------------------------------------------------
# Config default
# ---------------------------------------------------------------------------


def test_config_default_profile():
    settings = Settings()
    assert settings.extraction_profile == "auto"
