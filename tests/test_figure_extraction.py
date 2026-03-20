"""Tests for WP 6.1 — PDF Figure/Image Extraction.

Mocks Docling's picture objects to test figure extraction without a real PDF.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from ingestible.models.document import FigureRef, PageContent, ParsedDocument
from ingestible.pipeline.stage1_parsing import _extract_docling_figures

# ---------------------------------------------------------------------------
# Helpers — mock Docling picture objects
# ---------------------------------------------------------------------------


def _make_mock_picture(
    caption: str = "",
    label: str = "",
    classification: str = "",
    page_no: int | None = 1,
    uri: str | None = "image.png",
):
    """Build a mock PictureItem matching Docling's API surface."""
    pic = MagicMock()

    # Captions
    if caption:
        cap = MagicMock()
        cap.text = caption
        pic.captions = [cap]
    else:
        pic.captions = []

    pic.label = label
    pic.classification = classification

    # Provenance (page number)
    if page_no is not None:
        prov_entry = MagicMock()
        prov_entry.page_no = page_no
        prov_entry.page = page_no
        pic.prov = [prov_entry]
    else:
        pic.prov = []

    # Image reference
    if uri:
        image_ref = MagicMock()
        image_ref.uri = uri
        pic.image = image_ref
    else:
        pic.image = None

    return pic


def _make_mock_doc_obj(pictures=None):
    """Build a mock Docling document object with .pictures."""
    doc = MagicMock()
    doc.pictures = pictures or []
    return doc


# ---------------------------------------------------------------------------
# Tests — _extract_docling_figures
# ---------------------------------------------------------------------------


class TestExtractDoclingFigures:
    def test_no_pictures(self):
        doc = _make_mock_doc_obj(pictures=[])
        figs = _extract_docling_figures(doc)
        assert figs == []

    def test_no_pictures_attr(self):
        doc = MagicMock(spec=[])  # no .pictures attribute
        figs = _extract_docling_figures(doc)
        assert figs == []

    def test_single_figure_basic(self):
        pic = _make_mock_picture(caption="A chart", label="Figure 1", page_no=3)
        doc = _make_mock_doc_obj([pic])
        figs = _extract_docling_figures(doc)

        assert len(figs) == 1
        fig = figs[0]
        assert isinstance(fig, FigureRef)
        assert fig.figure_id == "fig-1"
        assert fig.caption == "A chart"
        assert fig.label == "Figure 1"
        assert fig.page_num == 3
        assert fig.filename == "fig-1.png"

    def test_multiple_figures(self):
        pics = [_make_mock_picture(caption=f"Fig {i}", page_no=i) for i in range(1, 4)]
        doc = _make_mock_doc_obj(pics)
        figs = _extract_docling_figures(doc)

        assert len(figs) == 3
        assert [f.figure_id for f in figs] == ["fig-1", "fig-2", "fig-3"]
        assert [f.page_num for f in figs] == [1, 2, 3]

    def test_figure_with_classification(self):
        pic = _make_mock_picture(classification="chart")
        doc = _make_mock_doc_obj([pic])
        figs = _extract_docling_figures(doc)

        assert figs[0].classification == "chart"

    def test_figure_without_caption(self):
        pic = _make_mock_picture(caption="", page_no=1)
        doc = _make_mock_doc_obj([pic])
        figs = _extract_docling_figures(doc)

        assert figs[0].caption == ""

    def test_figure_without_page(self):
        pic = _make_mock_picture(page_no=None)
        doc = _make_mock_doc_obj([pic])
        figs = _extract_docling_figures(doc)

        assert figs[0].page_num is None

    def test_figure_with_jpg_uri(self):
        pic = _make_mock_picture(uri="image.jpg")
        doc = _make_mock_doc_obj([pic])
        figs = _extract_docling_figures(doc)

        assert figs[0].filename == "fig-1.jpg"

    def test_figure_without_image_ref(self):
        pic = _make_mock_picture(uri=None)
        doc = _make_mock_doc_obj([pic])
        figs = _extract_docling_figures(doc)

        assert figs[0].filename == "fig-1.png"  # default extension


# ---------------------------------------------------------------------------
# Tests — FigureRef on PageContent
# ---------------------------------------------------------------------------


class TestFigureRefOnPageContent:
    def test_page_content_with_figure_refs(self):
        fig = FigureRef(figure_id="fig-1", filename="fig-1.png", caption="Test")
        page = PageContent(page_num=1, markdown="Hello", figures=[fig])

        assert len(page.figures) == 1
        assert isinstance(page.figures[0], FigureRef)
        assert page.figures[0].figure_id == "fig-1"

    def test_page_content_default_empty_figures(self):
        page = PageContent(page_num=1)
        assert page.figures == []

    def test_figure_ref_serialization(self):
        fig = FigureRef(
            figure_id="fig-1",
            filename="fig-1.png",
            caption="A diagram",
            label="Figure 1",
            page_num=5,
            classification="diagram",
        )
        data = fig.model_dump()
        assert data["figure_id"] == "fig-1"
        assert data["filename"] == "fig-1.png"
        assert data["caption"] == "A diagram"

        # Round-trip
        fig2 = FigureRef(**data)
        assert fig2 == fig


# ---------------------------------------------------------------------------
# Tests — Figure files on disk (orchestrator + storage)
# ---------------------------------------------------------------------------


class TestFigurePersistence:
    def test_save_figure_images_creates_directory(self, tmp_path):
        from ingestible.pipeline.orchestrator import _save_figure_images

        fig = FigureRef(figure_id="fig-1", filename="fig-1.png", page_num=1)
        page = PageContent(page_num=1, markdown="text", figures=[fig])
        parsed = ParsedDocument(title="Test", source_path="/test.pdf", pages=[page])

        doc_dir = tmp_path / "test-doc"
        doc_dir.mkdir()

        _save_figure_images(parsed, doc_dir)

        figures_dir = doc_dir / "figures"
        assert figures_dir.exists()
        assert (figures_dir / "fig-1.png").exists()

    def test_save_figure_images_skips_when_no_figures(self, tmp_path):
        from ingestible.pipeline.orchestrator import _save_figure_images

        page = PageContent(page_num=1, markdown="text")
        parsed = ParsedDocument(title="Test", source_path="/test.pdf", pages=[page])

        doc_dir = tmp_path / "test-doc"
        doc_dir.mkdir()

        _save_figure_images(parsed, doc_dir)

        assert not (doc_dir / "figures").exists()

    def test_figures_json_manifest(self, tmp_path):
        from ingestible.config import Settings
        from ingestible.models.chunks import (
            ChunkSet,
            L0Chunk,
        )
        from ingestible.models.document import DocumentStructure, StructureNode
        from ingestible.pipeline.stage6_storage import save_document

        settings = Settings(data_dir=tmp_path)
        doc_id = "fig-test"

        # Create figure files in expected location
        doc_dir = settings.documents_dir / doc_id / "figures"
        doc_dir.mkdir(parents=True)
        (doc_dir / "fig-1.png").write_bytes(b"\x89PNG")
        (doc_dir / "fig-2.jpg").write_bytes(b"\xff\xd8")

        chunks = ChunkSet(
            doc_id=doc_id,
            l0=L0Chunk(chunk_id=f"{doc_id}-L0", title="Figure Test"),
        )
        root = StructureNode(id=doc_id, title="Figure Test", level=0)
        structure = DocumentStructure(doc_id=doc_id, title="Figure Test", root=root)

        save_document(structure, chunks, settings)

        figures_json = settings.documents_dir / doc_id / "figures.json"
        assert figures_json.exists()

        data = json.loads(figures_json.read_text())
        assert "fig-1.png" in data["figures"]
        assert "fig-2.jpg" in data["figures"]
