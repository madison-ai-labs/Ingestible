"""Extraction profiles — document-type-specific tuning for chunking and enrichment."""

from __future__ import annotations

import logging
import re
from typing import Literal

from pydantic import BaseModel

from ingestible.models.document import ParsedDocument

logger = logging.getLogger(__name__)

ProfileName = Literal["paper", "article", "documentation", "general"]


class ExtractionProfile(BaseModel):
    """Controls chunking parameters and enrichment prompts per document type."""

    name: ProfileName

    # Chunking overrides (None = use global settings)
    max_chunk_tokens: int | None = None
    min_chunk_tokens: int | None = None
    chunking_strategy: str | None = None

    # Enrichment prompt customization
    l3_prompt_suffix: str = ""
    l0_prompt_suffix: str = ""

    # Feature flags
    extract_citations: bool = False
    extract_methodology: bool = True


PROFILES: dict[str, ExtractionProfile] = {
    "paper": ExtractionProfile(
        name="paper",
        max_chunk_tokens=400,
        chunking_strategy="semantic",
        extract_citations=True,
        extract_methodology=True,
        l3_prompt_suffix=(
            "This is from a scientific paper. Pay attention to claims, "
            "evidence, statistical results, and citation markers (e.g. [1], "
            "(Smith et al., 2024))."
        ),
        l0_prompt_suffix=(
            "This is a scientific paper. Identify the research methodology, "
            "key findings with evidence, and limitations explicitly. "
            "If this is not empirical research, leave methodology empty."
        ),
    ),
    "article": ExtractionProfile(
        name="article",
        extract_citations=False,
        extract_methodology=False,
        l3_prompt_suffix=(
            "This is a journalistic or editorial article. Focus on arguments, "
            "opinions, and supporting evidence."
        ),
        l0_prompt_suffix=(
            "This is an article. Focus on the main argument, supporting "
            "points, and conclusion. Leave methodology empty."
        ),
    ),
    "documentation": ExtractionProfile(
        name="documentation",
        max_chunk_tokens=600,
        min_chunk_tokens=150,
        extract_citations=False,
        extract_methodology=False,
        l3_prompt_suffix=(
            "This is technical documentation. Focus on API names, "
            "configuration options, procedures, and prerequisites."
        ),
        l0_prompt_suffix=(
            "This is technical documentation. Summarize what it covers, "
            "prerequisites, and key APIs or concepts. Leave methodology empty."
        ),
    ),
    "general": ExtractionProfile(
        name="general",
        extract_citations=False,
        extract_methodology=False,
    ),
}

# Patterns used for heuristic profile detection
_PAPER_HEADINGS = re.compile(
    r"\b(abstract|introduction|related work|methodology|methods|results|"
    r"discussion|conclusion|references|bibliography|acknowledgements)\b",
    re.IGNORECASE,
)

_DOC_HEADINGS = re.compile(
    r"\b(api|installation|configuration|getting started|usage|quickstart|"
    r"setup|reference|tutorial|guide|changelog)\b",
    re.IGNORECASE,
)

_CODE_BLOCK_RE = re.compile(r"```")


def detect_profile(parsed: ParsedDocument) -> ProfileName:
    """Detect the extraction profile from a parsed document using heuristics.

    Checks TOC headings, content patterns, and source format.
    """
    toc_text = parsed.toc if hasattr(parsed, "toc") and parsed.toc else ""
    if isinstance(toc_text, list):
        toc_text = " ".join(str(t) for t in toc_text)

    # Grab first ~3000 chars for pattern matching
    content_sample = parsed.full_markdown[:3000] if hasattr(parsed, "full_markdown") else ""

    combined = f"{toc_text} {content_sample}"

    # Paper detection: look for academic section headings
    paper_hits = len(_PAPER_HEADINGS.findall(combined))
    if paper_hits >= 3:
        logger.info("Profile auto-detected: paper (matched %d academic headings)", paper_hits)
        return "paper"

    # Documentation detection: format or heading signals
    source_fmt = getattr(parsed, "source_format", "")
    doc_hits = len(_DOC_HEADINGS.findall(combined))
    code_blocks = len(_CODE_BLOCK_RE.findall(content_sample))

    if doc_hits >= 2 or (source_fmt in (".rst", ".adoc") and code_blocks >= 2):
        logger.info("Profile auto-detected: documentation")
        return "documentation"

    if code_blocks >= 3 and source_fmt in (".md", ".rst", ".adoc", ".html"):
        logger.info("Profile auto-detected: documentation (code-heavy)")
        return "documentation"

    # Article: if it's HTML/markdown with no strong signals, likely an article
    if source_fmt in (".html", ".md") and paper_hits < 2 and doc_hits < 2:
        logger.info("Profile auto-detected: article")
        return "article"

    logger.info("Profile auto-detected: general")
    return "general"
