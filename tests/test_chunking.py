from ingestible.config import Settings
from ingestible.models.document import DocumentStructure, StructureNode
from ingestible.pipeline.stage3_chunking import chunk_document


def _make_structure(sections: list[tuple[str, str]]) -> DocumentStructure:
    """Helper: create a structure with chapter > sections."""
    children = []
    for title, content in sections:
        children.append(StructureNode(id=f"sec-{title}", title=title, level=2, content=content))
    root = StructureNode(
        id="root",
        title="Test Doc",
        level=0,
        page_end=10,
        children=[
            StructureNode(
                id="ch1",
                title="Chapter 1",
                level=1,
                page_start=1,
                page_end=10,
                children=children,
            )
        ],
    )
    return DocumentStructure(doc_id="test", title="Test Doc", root=root)


def test_basic_chunking(tmp_path):
    settings = Settings(data_dir=tmp_path, max_chunk_tokens=50, min_chunk_tokens=10)
    content = "This is a paragraph about topic A.\n\nThis is another paragraph about topic B.\n\nAnd a third paragraph about topic C."
    structure = _make_structure([("Intro", content)])
    chunks = chunk_document(structure, settings)

    assert chunks.doc_id == "test"
    assert chunks.l0.title == "Test Doc"
    assert len(chunks.l1_chunks) == 1
    assert len(chunks.l2_chunks) == 1
    assert len(chunks.l3_chunks) >= 1


def test_empty_content(tmp_path):
    settings = Settings(data_dir=tmp_path)
    structure = _make_structure([("Empty", "")])
    chunks = chunk_document(structure, settings)
    # Should not crash, may produce 0 L3 chunks for the empty section
    assert chunks.l0.title == "Test Doc"
