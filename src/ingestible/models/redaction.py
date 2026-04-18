"""Redaction data models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class RedactedEntity(BaseModel):
    entity_type: str
    original: str
    replacement: str
    page_num: int


class RedactionManifest(BaseModel):
    """Produced by Stage 1d. Records every entity that was redacted and the
    pseudonym map used, so privileged callers can de-anonymize if needed."""

    doc_id: str
    mode: Literal["placeholder", "pseudonymize", "suppress"]
    entity_types: list[str]
    entities: list[RedactedEntity] = Field(default_factory=list)
    # original_text → pseudonym, populated only in pseudonymize mode
    pseudonym_map: dict[str, str] = Field(default_factory=dict)
    total_redactions: int = 0
    created_at: str = ""
