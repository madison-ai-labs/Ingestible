from ingestible.models.document import PageContent, ParsedDocument, TOCEntry
from ingestible.pipeline.stage2_structure import detect_structure


def test_structure_from_toc():
    doc = ParsedDocument(
        title="Test Book",
        source_path="/test.pdf",
        total_pages=100,
        toc=[
            TOCEntry(level=1, title="Chapter 1: Intro", page=1),
            TOCEntry(level=2, title="1.1 Background", page=1),
            TOCEntry(level=2, title="1.2 Scope", page=5),
            TOCEntry(level=1, title="Chapter 2: Methods", page=10),
            TOCEntry(level=2, title="2.1 Approach", page=10),
        ],
        pages=[PageContent(page_num=i, markdown=f"Content for page {i}") for i in range(1, 101)],
    )
    structure = detect_structure(doc, "test-doc")
    assert structure.doc_id == "test-doc"
    assert structure.title == "Test Book"
    assert len(structure.root.children) == 2  # 2 chapters
    assert len(structure.root.children[0].children) == 2  # 2 sections in ch1


def test_structure_no_toc():
    doc = ParsedDocument(
        title="Flat Doc",
        source_path="/flat.pdf",
        total_pages=1,
        pages=[
            PageContent(
                page_num=1,
                markdown="# Introduction\n\nSome text.\n\n## Details\n\nMore text.",
            )
        ],
    )
    structure = detect_structure(doc, "flat-doc")
    # Should detect headings from markdown
    assert structure.root.children  # at least one child detected
