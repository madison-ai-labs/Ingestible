"""Edge-case tests for the chunking pipeline.

Covers extreme inputs: large documents, deep nesting, tiny/empty sections,
very long content, Unicode/special chars, and table-heavy content.
"""

from __future__ import annotations

import time

from ingestible.config import Settings
from ingestible.models.document import DocumentStructure, StructureNode
from ingestible.pipeline.stage3_chunking import chunk_document
from ingestible.utils.tokens import count_tokens

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_structure(
    doc_id: str,
    title: str,
    chapters: list[StructureNode],
) -> DocumentStructure:
    root = StructureNode(
        id="root",
        title=title,
        level=0,
        page_end=len(chapters),
        children=chapters,
    )
    return DocumentStructure(doc_id=doc_id, title=title, root=root)


# ---------------------------------------------------------------------------
# 1. Large document (100 chapters)
# ---------------------------------------------------------------------------


def test_large_document_100_chapters(tmp_path):
    """100 chapters x 2 sections x 3 paragraphs — verify counts and speed."""
    para = "Agents use tools to interact with systems. Protocol standardises communication."
    section_body = "\n\n".join([para] * 3)

    chapters = []
    for ci in range(100):
        sections = []
        for si in range(2):
            sections.append(
                StructureNode(
                    id=f"ch{ci}-sec{si}",
                    title=f"Section {ci}.{si}",
                    level=2,
                    content=section_body,
                    page_start=ci * 2 + si,
                    page_end=ci * 2 + si + 1,
                )
            )
        chapters.append(
            StructureNode(
                id=f"ch{ci}",
                title=f"Chapter {ci}",
                level=1,
                page_start=ci * 2,
                page_end=ci * 2 + 2,
                children=sections,
            )
        )

    structure = _make_structure("large-100ch", "Large Document", chapters)
    settings = Settings(data_dir=tmp_path, max_chunk_tokens=500, min_chunk_tokens=100)

    start = time.perf_counter()
    chunks = chunk_document(structure, settings)
    elapsed = time.perf_counter() - start

    assert len(chunks.l1_chunks) == 100
    assert len(chunks.l2_chunks) == 200
    assert len(chunks.l3_chunks) > 0

    # No orphans
    l1_ids = {c.chunk_id for c in chunks.l1_chunks}
    l2_ids = {c.chunk_id for c in chunks.l2_chunks}
    assert all(c.parent_chapter_id in l1_ids for c in chunks.l2_chunks)
    assert all(c.parent_section_id in l2_ids for c in chunks.l3_chunks)

    assert elapsed < 30.0, f"Took {elapsed:.1f}s, exceeds 30s limit"


# ---------------------------------------------------------------------------
# 2. Deeply nested structure (5+ levels)
# ---------------------------------------------------------------------------


def test_deeply_nested_structure(tmp_path):
    """Structure with 6 levels of nesting — chunker should handle gracefully."""
    # Build bottom-up: level 5 → 4 → 3 → 2 → 1
    # The chunker only processes levels 0-2 as structural; deeper levels
    # get their content rolled up into level-2 nodes. So put content at
    # levels the chunker actually processes.
    leaf = StructureNode(
        id="depth-5",
        title="Leaf Node",
        level=5,
        content="This is the deeply nested leaf content with enough words to form a chunk.",
        page_start=1,
        page_end=1,
    )
    current = leaf
    for depth in range(4, 0, -1):
        current = StructureNode(
            id=f"depth-{depth}",
            title=f"Level {depth} Node",
            level=depth,
            page_start=1,
            page_end=1,
            children=[current],
            content=f"Content at level {depth}. Some additional text to ensure there is material."
            if depth >= 2
            else "",
        )

    structure = _make_structure("deep-nested", "Deeply Nested Doc", [current])
    settings = Settings(data_dir=tmp_path, max_chunk_tokens=500, min_chunk_tokens=10)

    chunks = chunk_document(structure, settings)

    # Should produce output without crashing
    assert chunks.l1_chunks is not None
    assert len(chunks.l1_chunks) >= 1

    # Level 2+ content should be captured — the chunker processes level-2 nodes
    # and may flatten deeper levels into them
    all_l3_content = " ".join(c.content for c in chunks.l3_chunks)
    all_l2_content = " ".join(c.content for c in chunks.l2_chunks)
    all_content = all_l3_content + " " + all_l2_content

    # At minimum, level-2 content should appear
    assert "Content at level 2" in all_content, "Level-2 content missing from output"
    # The chunker should produce at least one L3 chunk
    assert len(chunks.l3_chunks) >= 1, "No L3 chunks from deeply nested structure"


# ---------------------------------------------------------------------------
# 3. Single-sentence sections
# ---------------------------------------------------------------------------


def test_single_sentence_sections(tmp_path):
    """Sections with only one short sentence each — no empty chunks allowed."""
    sentences = [
        "Hello world.",
        "Short section.",
        "Tiny text.",
        "Another one.",
        "Last line.",
    ]
    sections = [
        StructureNode(
            id=f"sec{i}",
            title=f"Section {i}",
            level=2,
            content=s,
            page_start=i,
            page_end=i + 1,
        )
        for i, s in enumerate(sentences)
    ]
    chapter = StructureNode(
        id="ch0",
        title="Chapter 0",
        level=1,
        page_start=0,
        page_end=len(sentences),
        children=sections,
    )
    structure = _make_structure("single-sentence", "Single Sentence Doc", [chapter])
    settings = Settings(data_dir=tmp_path, max_chunk_tokens=500, min_chunk_tokens=5)

    chunks = chunk_document(structure, settings)

    # No empty L3 chunks
    for c in chunks.l3_chunks:
        assert c.content.strip(), f"Empty L3 chunk: {c.chunk_id}"

    # All input sentences should appear in output
    all_l3_text = " ".join(c.content for c in chunks.l3_chunks)
    for s in sentences:
        assert s in all_l3_text, f"Missing sentence: {s!r}"


# ---------------------------------------------------------------------------
# 4. Empty sections
# ---------------------------------------------------------------------------


def test_empty_sections(tmp_path):
    """Mix of empty and non-empty sections — empty ones produce no L3 chunks."""
    sections = [
        StructureNode(id="sec0", title="Empty One", level=2, content="", page_start=0, page_end=1),
        StructureNode(
            id="sec1",
            title="Has Content",
            level=2,
            content="This section has real content that should produce chunks.",
            page_start=1,
            page_end=2,
        ),
        StructureNode(
            id="sec2",
            title="Whitespace Only",
            level=2,
            content="   \n\n  \t  ",
            page_start=2,
            page_end=3,
        ),
        StructureNode(
            id="sec3",
            title="Also Content",
            level=2,
            content="Another section with meaningful text for chunking.",
            page_start=3,
            page_end=4,
        ),
    ]
    chapter = StructureNode(
        id="ch0", title="Chapter", level=1, page_start=0, page_end=4, children=sections
    )
    structure = _make_structure("empty-sections", "Empty Sections Doc", [chapter])
    settings = Settings(data_dir=tmp_path, max_chunk_tokens=500, min_chunk_tokens=5)

    chunks = chunk_document(structure, settings)

    # Find L2 chunks for empty sections
    l2_by_title = {c.title: c for c in chunks.l2_chunks}

    # Non-empty sections should have L3 children
    for title in ("Has Content", "Also Content"):
        if title in l2_by_title:
            l2 = l2_by_title[title]
            assert len(l2.children_ids) > 0, f"Section '{title}' should have L3 children"

    # Empty/whitespace sections should have no L3 children
    for title in ("Empty One", "Whitespace Only"):
        if title in l2_by_title:
            l2 = l2_by_title[title]
            assert len(l2.children_ids) == 0, (
                f"Section '{title}' should have no L3 children, got {l2.children_ids}"
            )

    # No empty L3 chunks anywhere
    for c in chunks.l3_chunks:
        assert c.content.strip(), f"Empty L3 chunk found: {c.chunk_id}"


# ---------------------------------------------------------------------------
# 5. Very long single section (10,000+ words)
# ---------------------------------------------------------------------------


def test_very_long_section(tmp_path):
    """Single section with ~10,000 words — must split into multiple L3 chunks."""
    # Build ~10k words: 500 sentences of ~20 words each
    sentence = "The quick brown fox jumps over the lazy dog and runs across the wide green meadow every single day without fail. "
    # Build paragraphs of 5 sentences each separated by blank lines (so the chunker splits)
    paragraph = sentence * 5
    long_content = "\n\n".join([paragraph] * 100)  # 100 paragraphs × 5 sentences × 20 words

    word_count = len(long_content.split())
    assert word_count >= 10000, f"Content too short: {word_count} words"

    section = StructureNode(
        id="sec0",
        title="Long Section",
        level=2,
        content=long_content,
        page_start=0,
        page_end=20,
    )
    chapter = StructureNode(
        id="ch0", title="Chapter", level=1, page_start=0, page_end=20, children=[section]
    )
    structure = _make_structure("long-section", "Long Section Doc", [chapter])
    max_tokens = 500
    settings = Settings(data_dir=tmp_path, max_chunk_tokens=max_tokens, min_chunk_tokens=100)

    chunks = chunk_document(structure, settings)

    # Must split into multiple chunks
    assert len(chunks.l3_chunks) > 1, (
        f"10k-word section should split into multiple chunks, got {len(chunks.l3_chunks)}"
    )

    # Check max_chunk_tokens with 1.5x tolerance
    tolerance = max_tokens * 1.5
    for c in chunks.l3_chunks:
        tokens = count_tokens(c.content)
        assert tokens <= tolerance, (
            f"Chunk {c.chunk_id} has {tokens} tokens, exceeds {tolerance} (1.5x max)"
        )

    # Total output should preserve all input content (check by char coverage)
    output_text = " ".join(c.content for c in chunks.l3_chunks)
    # Allow some variance for overlap/formatting, but majority of content should be there
    assert len(output_text) >= len(long_content) * 0.8, "Lost too much content in splitting"


# ---------------------------------------------------------------------------
# 6. Unicode and special characters
# ---------------------------------------------------------------------------


def test_unicode_and_special_characters(tmp_path):
    """CJK, emoji, RTL, math symbols, code blocks — nothing corrupted or dropped."""
    sections_data = [
        (
            "CJK",
            "Chinese: \u4f60\u597d\u4e16\u754c\u3002 Japanese: \u3053\u3093\u306b\u3061\u306f\u4e16\u754c\u3002 Korean: \uc548\ub155\ud558\uc138\uc694 \uc138\uacc4.",
        ),
        (
            "Emoji",
            "Rocket launch \U0001f680 was a success \u2705. Team celebrated \U0001f389 with cake \U0001f382.",
        ),
        (
            "RTL",
            "Arabic: \u0645\u0631\u062d\u0628\u0627 \u0628\u0627\u0644\u0639\u0627\u0644\u0645. Hebrew: \u05e9\u05dc\u05d5\u05dd \u05e2\u05d5\u05dc\u05dd.",
        ),
        (
            "Math",
            "Euler's identity: e^{i\u03c0} + 1 = 0. The integral \u222b f(x)dx converges. \u2200x \u2208 \u211d: x\u00b2 \u2265 0.",
        ),
        ("Code", "```python\ndef hello():\n    print('Hello, world!')\n```\n\nInline: `x = 42`"),
    ]

    sections = []
    for i, (title, content) in enumerate(sections_data):
        sections.append(
            StructureNode(
                id=f"sec{i}",
                title=title,
                level=2,
                content=content,
                page_start=i,
                page_end=i + 1,
            )
        )

    chapter = StructureNode(
        id="ch0", title="Unicode Chapter", level=1, page_start=0, page_end=5, children=sections
    )
    structure = _make_structure("unicode-doc", "Unicode Test", [chapter])
    settings = Settings(data_dir=tmp_path, max_chunk_tokens=500, min_chunk_tokens=5)

    chunks = chunk_document(structure, settings)

    all_l3 = " ".join(c.content for c in chunks.l3_chunks)

    # CJK preserved
    assert "\u4f60\u597d" in all_l3, "CJK characters lost"
    assert "\uc548\ub155" in all_l3, "Korean characters lost"

    # Emoji preserved
    assert "\U0001f680" in all_l3, "Emoji lost"

    # RTL preserved
    assert "\u0645\u0631\u062d\u0628\u0627" in all_l3, "Arabic text lost"

    # Math preserved
    assert "\u03c0" in all_l3, "Math symbols lost"
    assert "\u222b" in all_l3, "Integral symbol lost"

    # Code preserved
    assert "def hello():" in all_l3, "Code block lost"
    assert "```" in all_l3, "Backtick fencing lost"

    # All chunks should have positive token counts
    for c in chunks.l3_chunks:
        assert count_tokens(c.content) > 0, f"Chunk {c.chunk_id} has 0 tokens"


# ---------------------------------------------------------------------------
# 7. Table-heavy content
# ---------------------------------------------------------------------------


def test_table_heavy_content(tmp_path):
    """Sections with only markdown tables — pipes survive, tables stay atomic."""
    table1 = (
        "| Name | Age | City |\n"
        "| --- | --- | --- |\n"
        "| Alice | 30 | London |\n"
        "| Bob | 25 | Paris |\n"
        "| Carol | 35 | Tokyo |"
    )
    table2 = (
        "| Product | Price | Stock |\n"
        "| --- | --- | --- |\n"
        "| Widget | $10 | 500 |\n"
        "| Gadget | $25 | 200 |\n"
        "| Gizmo | $15 | 350 |"
    )
    table3 = (
        "| Language | Year | Creator |\n"
        "| --- | --- | --- |\n"
        "| Python | 1991 | van Rossum |\n"
        "| Rust | 2010 | Hoare |\n"
        "| Go | 2009 | Pike |"
    )

    content = f"{table1}\n\n{table2}\n\n{table3}"

    section = StructureNode(
        id="sec0",
        title="Tables Section",
        level=2,
        content=content,
        page_start=0,
        page_end=1,
    )
    chapter = StructureNode(
        id="ch0", title="Tables Chapter", level=1, page_start=0, page_end=1, children=[section]
    )
    structure = _make_structure("tables-doc", "Table Heavy Doc", [chapter])
    settings = Settings(data_dir=tmp_path, max_chunk_tokens=500, min_chunk_tokens=5)

    chunks = chunk_document(structure, settings)

    all_l3 = "\n".join(c.content for c in chunks.l3_chunks)

    # Pipe characters survive
    assert "|" in all_l3, "Table pipe characters lost"

    # Key data from each table survives
    assert "Alice" in all_l3, "Table 1 data lost"
    assert "Widget" in all_l3, "Table 2 data lost"
    assert "Python" in all_l3, "Table 3 data lost"

    # Tables should not be split mid-row — check that rows are intact
    for c in chunks.l3_chunks:
        lines = c.content.split("\n")
        for line in lines:
            if line.strip().startswith("|") and line.strip().endswith("|"):
                # A pipe-delimited row should have consistent column count
                cols = [col.strip() for col in line.strip().strip("|").split("|")]
                assert len(cols) >= 2, f"Broken table row: {line!r}"
