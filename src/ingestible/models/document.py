from __future__ import annotations

from pydantic import BaseModel, Field

from ingestible.models.metadata import DocumentMetadata


class TOCEntry(BaseModel):
    level: int
    title: str
    page: int | None = None


class FigureRef(BaseModel):
    """Reference to an extracted figure/image from a document."""

    figure_id: str
    filename: str
    caption: str = ""
    label: str = ""
    page_num: int | None = None
    classification: str = ""


class PageContent(BaseModel):
    page_num: int
    markdown: str = ""
    tables: list[str] = Field(default_factory=list)
    figures: list[FigureRef] = Field(default_factory=list)
    has_code_blocks: bool = False

    # Timestamps (audio/video sources only, in seconds)
    timestamp_start: float | None = None
    timestamp_end: float | None = None


class ParsedDocument(BaseModel):
    """Output of Stage 1 — raw parsed document."""

    title: str
    source_path: str
    source_format: str = "pdf"
    total_pages: int = 0
    detected_language: str = "en"
    toc: list[TOCEntry] = Field(default_factory=list)
    pages: list[PageContent] = Field(default_factory=list)
    metadata: DocumentMetadata | None = None

    # Content block classifications (populated by Stage 1c)
    block_classifications: dict[str, list[tuple[str, str]]] = Field(default_factory=dict)

    @property
    def full_markdown(self) -> str:
        return "\n\n".join(p.markdown for p in self.pages if p.markdown)

    @property
    def avg_chars_per_page(self) -> float:
        if not self.pages:
            return 0.0
        return sum(len(p.markdown) for p in self.pages) / len(self.pages)


class StructureNode(BaseModel):
    """A node in the document hierarchy tree."""

    id: str
    title: str
    level: int  # 0=document, 1=chapter/part, 2=section, 3=subsection
    page_start: int | None = None
    page_end: int | None = None
    content: str = ""
    children: list[StructureNode] = Field(default_factory=list)
    is_special: bool = False  # index, glossary, bibliography, appendix

    def walk(self):
        """Yield self and all descendants depth-first."""
        yield self
        for child in self.children:
            yield from child.walk()


class DocumentStructure(BaseModel):
    """Output of Stage 2 — hierarchy tree."""

    doc_id: str
    title: str
    root: StructureNode
