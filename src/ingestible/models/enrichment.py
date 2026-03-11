from __future__ import annotations

from pydantic import BaseModel, Field


class L3Enrichment(BaseModel):
    """LLM output schema for passage-level enrichment."""

    summary: str = ""
    concepts: list[str] = Field(default_factory=list)
    hypothetical_questions: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    difficulty_level: str = "intermediate"
    depends_on: list[str] = Field(default_factory=list)
    cross_references: list[str] = Field(default_factory=list)


class L2Enrichment(BaseModel):
    """LLM output schema for section-level enrichment."""

    section_summary: str = ""
    key_points: list[str] = Field(default_factory=list)
    concepts_introduced: list[str] = Field(default_factory=list)


class L1Enrichment(BaseModel):
    """LLM output schema for chapter-level enrichment."""

    chapter_summary: str = ""
    main_topics: list[str] = Field(default_factory=list)
    learning_objectives: list[str] = Field(default_factory=list)
    prerequisite_chapters: list[str] = Field(default_factory=list)
    key_takeaways: list[str] = Field(default_factory=list)


class L0Enrichment(BaseModel):
    """LLM output schema for document-level enrichment."""

    domain: str = ""
    key_concepts: list[str] = Field(default_factory=list)
