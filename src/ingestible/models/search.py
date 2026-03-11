from __future__ import annotations

from pydantic import BaseModel, Field


class SearchResult(BaseModel):
    chunk_id: str
    content: str
    summary: str = ""
    score: float = 0.0
    chapter: str = ""
    section: str = ""
    page_start: int | None = None
    page_end: int | None = None
    match_sources: list[str] = Field(default_factory=list)  # "vector", "bm25", "concept"
    doc_id: str = ""
    doc_title: str = ""


class SearchResponse(BaseModel):
    doc_id: str
    query: str
    results: list[SearchResult] = Field(default_factory=list)
    total_candidates: int = 0


class CorpusSearchResponse(BaseModel):
    """Response from cross-document corpus search."""

    query: str
    results: list[SearchResult] = Field(default_factory=list)
    total_candidates: int = 0
    documents_searched: int = 0
