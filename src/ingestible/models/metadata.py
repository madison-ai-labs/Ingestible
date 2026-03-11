"""Document metadata model — extracted from PDF/DOCX/HTML file properties."""

from __future__ import annotations

from pydantic import BaseModel, Field


class DocumentMetadata(BaseModel):
    """Metadata extracted from document file properties (not content analysis)."""

    author: str = ""
    creator: str = ""
    producer: str = ""
    subject: str = ""
    keywords: list[str] = Field(default_factory=list)
    creation_date: str = ""
    modification_date: str = ""
    language: str = ""
    page_count: int = 0
    word_count: int = 0
