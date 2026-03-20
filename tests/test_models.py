from ingestible.models.chunks import ChunkSet, L0Chunk
from ingestible.models.document import (
    PageContent,
    ParsedDocument,
    StructureNode,
)
from ingestible.models.search import SearchResult


def test_parsed_document_properties():
    doc = ParsedDocument(
        title="Test",
        source_path="/test.pdf",
        total_pages=2,
        pages=[
            PageContent(page_num=1, markdown="Hello world"),
            PageContent(page_num=2, markdown="Page two content"),
        ],
    )
    assert doc.full_markdown == "Hello world\n\nPage two content"
    assert doc.avg_chars_per_page == (11 + 16) / 2


def test_structure_node_walk():
    root = StructureNode(
        id="root",
        title="Doc",
        level=0,
        children=[
            StructureNode(
                id="ch1",
                title="Chapter 1",
                level=1,
                children=[
                    StructureNode(id="s1", title="Section 1", level=2),
                ],
            ),
            StructureNode(id="ch2", title="Chapter 2", level=1),
        ],
    )
    ids = [n.id for n in root.walk()]
    assert ids == ["root", "ch1", "s1", "ch2"]


def test_chunk_set_creation():
    l0 = L0Chunk(chunk_id="doc-L0", title="Test Doc")
    cs = ChunkSet(doc_id="doc", l0=l0)
    assert cs.doc_id == "doc"
    assert len(cs.l3_chunks) == 0


def test_search_result():
    r = SearchResult(
        chunk_id="c1",
        content="test content",
        score=0.95,
        match_sources=["vector", "bm25"],
    )
    assert r.score == 0.95
    assert "vector" in r.match_sources
