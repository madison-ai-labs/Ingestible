from ingestible.config import Settings
from ingestible.models.chunks import (
    ChunkPosition,
    ChunkSet,
    L0Chunk,
    L1Chunk,
    L2Chunk,
    L3Chunk,
)
from ingestible.models.document import DocumentStructure, StructureNode
from ingestible.pipeline.stage6_storage import (
    list_documents,
    load_chunks,
    load_document_meta,
    save_document,
)


def _make_test_data():
    structure = DocumentStructure(
        doc_id="test-doc",
        title="Test Document",
        root=StructureNode(id="root", title="Test Document", level=0),
    )
    chunks = ChunkSet(
        doc_id="test-doc",
        l0=L0Chunk(
            chunk_id="test-doc-L0",
            title="Test Document",
            total_pages=10,
            total_chapters=1,
            total_sections=1,
            total_passages=2,
        ),
        l1_chunks=[
            L1Chunk(
                chunk_id="ch1",
                title="Chapter 1",
                content="Chapter content",
                children_ids=["sec1"],
            )
        ],
        l2_chunks=[
            L2Chunk(
                chunk_id="sec1",
                title="Section 1",
                content="Section content",
                parent_chapter_id="ch1",
                children_ids=["p1", "p2"],
            )
        ],
        l3_chunks=[
            L3Chunk(
                chunk_id="p1",
                content="First passage",
                parent_section_id="sec1",
                position=ChunkPosition(chapter="ch1", section="sec1", index=0),
            ),
            L3Chunk(
                chunk_id="p2",
                content="Second passage",
                parent_section_id="sec1",
                position=ChunkPosition(chapter="ch1", section="sec1", index=1),
            ),
        ],
    )
    return structure, chunks


def test_save_and_load(tmp_path):
    settings = Settings(data_dir=tmp_path)
    structure, chunks = _make_test_data()

    doc_dir = save_document(structure, chunks, settings)
    assert doc_dir.exists()
    assert (doc_dir / "meta.json").exists()
    assert (doc_dir / "structure.json").exists()

    # Load back
    meta = load_document_meta(doc_dir)
    assert meta["doc_id"] == "test-doc"
    assert meta["title"] == "Test Document"

    loaded = load_chunks(doc_dir)
    assert loaded.doc_id == "test-doc"
    assert len(loaded.l1_chunks) == 1
    assert len(loaded.l2_chunks) == 1
    assert len(loaded.l3_chunks) == 2
    assert loaded.l3_chunks[0].content == "First passage"


def test_list_documents(tmp_path):
    settings = Settings(data_dir=tmp_path)
    structure, chunks = _make_test_data()
    save_document(structure, chunks, settings)

    docs = list_documents(settings)
    assert len(docs) == 1
    assert docs[0]["doc_id"] == "test-doc"
