from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ChunkPosition(BaseModel):
    chapter: str = ""
    section: str = ""
    index: int = 0


class L3Chunk(BaseModel):
    """Passage-level chunk (~250-500 tokens). Primary retrieval unit for semantic search."""

    chunk_id: str
    content: str
    content_hash: str = ""
    page_start: int | None = None
    page_end: int | None = None
    position: ChunkPosition = Field(default_factory=ChunkPosition)
    parent_section_id: str = ""
    position_in_section: Literal["first", "middle", "last", "only"] = "only"

    # Context prefix (populated by Stage 3c — contextual chunking)
    context_prefix: str = ""

    # Enrichment fields (populated by Stage 4)
    summary: str = ""
    concepts: list[str] = Field(default_factory=list)
    hypothetical_questions: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    difficulty_level: str = ""
    depends_on: list[str] = Field(default_factory=list)
    cross_references: list[str] = Field(default_factory=list)


class L2Chunk(BaseModel):
    """Section-level chunk (~200-400 tokens)."""

    chunk_id: str
    title: str
    content: str
    page_start: int | None = None
    page_end: int | None = None
    parent_chapter_id: str = ""
    children_ids: list[str] = Field(default_factory=list)

    # Enrichment fields
    section_summary: str = ""
    key_points: list[str] = Field(default_factory=list)
    concepts_introduced: list[str] = Field(default_factory=list)


class L1Chunk(BaseModel):
    """Chapter-level chunk (~300-500 tokens)."""

    chunk_id: str
    title: str
    content: str
    page_start: int | None = None
    page_end: int | None = None
    children_ids: list[str] = Field(default_factory=list)

    # Enrichment fields
    chapter_summary: str = ""
    main_topics: list[str] = Field(default_factory=list)
    learning_objectives: list[str] = Field(default_factory=list)
    prerequisite_chapters: list[str] = Field(default_factory=list)
    key_takeaways: list[str] = Field(default_factory=list)


class L0Chunk(BaseModel):
    """Document-level chunk (~500 tokens). Always returned as context."""

    chunk_id: str
    title: str
    author: str = ""
    domain: str = ""
    creation_date: str = ""
    source_language: str = ""
    toc_summary: str = ""
    key_concepts: list[str] = Field(default_factory=list)
    total_pages: int = 0
    total_chapters: int = 0
    total_sections: int = 0
    total_passages: int = 0


class ChunkSet(BaseModel):
    """Complete set of chunks for a document (output of Stage 3)."""

    doc_id: str
    l0: L0Chunk
    l1_chunks: list[L1Chunk] = Field(default_factory=list)
    l2_chunks: list[L2Chunk] = Field(default_factory=list)
    l3_chunks: list[L3Chunk] = Field(default_factory=list)
