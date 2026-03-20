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
    cited_references: list[str] = Field(default_factory=list)


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
    executive_summary: str = ""
    key_findings: list[str] = Field(default_factory=list)
    methodology: str = ""
    limitations: str = ""
    document_type: str = ""
    target_audience: str = ""


class Citation(BaseModel):
    """A structured citation extracted from the document."""

    citation_id: str = ""
    authors: list[str] = Field(default_factory=list)
    title: str = ""
    year: str = ""
    venue: str = ""
    doi: str = ""
    raw_text: str = ""
    inline_references: list[str] = Field(default_factory=list)


class CitationList(BaseModel):
    """LLM output schema for batch citation extraction."""

    citations: list[Citation] = Field(default_factory=list)


class KGTriple(BaseModel):
    """A single (subject, predicate, object) triple for knowledge graph construction."""

    subject: str = ""
    subject_type: str = ""  # e.g. "Person", "Concept", "Method", "Organization"
    predicate: str = ""  # e.g. "uses", "is_a", "part_of", "authored_by"
    object: str = ""
    object_type: str = ""
    confidence: float = Field(
        default=1.0, ge=0.0, le=1.0
    )  # 0.0–1.0, how confident the extraction is
    source_chunk_id: str = ""  # populated after extraction


class KGTripleList(BaseModel):
    """LLM output schema for knowledge graph triple extraction."""

    triples: list[KGTriple] = Field(default_factory=list)
