"""Extraction profiles — document-type-specific tuning for chunking and enrichment."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field

from ingestible.models.document import ParsedDocument

if TYPE_CHECKING:
    from ingestible.config import Settings

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
    extract_knowledge_graph: bool = False


PROFILES: dict[str, ExtractionProfile] = {
    "paper": ExtractionProfile(
        name="paper",
        max_chunk_tokens=400,
        chunking_strategy="semantic",
        extract_citations=True,
        extract_methodology=True,
        extract_knowledge_graph=True,
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
        extract_knowledge_graph=True,
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


class _DetectionResult:
    """Internal: heuristic detection result with confidence."""

    def __init__(self, profile: ProfileName, confidence: str):
        self.profile = profile
        self.confidence: str = confidence  # "high" or "low"


def _detect_heuristic(parsed: ParsedDocument) -> _DetectionResult:
    """Run heuristic detection. Returns profile name + confidence level."""
    toc_text = parsed.toc if hasattr(parsed, "toc") and parsed.toc else ""
    if isinstance(toc_text, list):
        toc_text = " ".join(str(t) for t in toc_text)

    content_sample = parsed.full_markdown[:3000] if hasattr(parsed, "full_markdown") else ""
    combined = f"{toc_text} {content_sample}"

    paper_hits = len(_PAPER_HEADINGS.findall(combined))
    if paper_hits >= 3:
        logger.info("Profile auto-detected: paper (matched %d academic headings)", paper_hits)
        return _DetectionResult("paper", "high")

    source_fmt = getattr(parsed, "source_format", "")
    doc_hits = len(_DOC_HEADINGS.findall(combined))
    code_blocks = len(_CODE_BLOCK_RE.findall(content_sample))

    if doc_hits >= 2 or (source_fmt in (".rst", ".adoc") and code_blocks >= 2):
        logger.info("Profile auto-detected: documentation")
        return _DetectionResult("documentation", "high")

    if code_blocks >= 3 and source_fmt in (".md", ".rst", ".adoc", ".html"):
        logger.info("Profile auto-detected: documentation (code-heavy)")
        return _DetectionResult("documentation", "high")

    if source_fmt in (".html", ".md") and paper_hits < 2 and doc_hits < 2:
        logger.info("Profile auto-detected: article")
        return _DetectionResult("article", "high" if paper_hits == 0 else "low")

    logger.info("Profile auto-detected: general (low confidence)")
    return _DetectionResult("general", "low")


def detect_profile(parsed: ParsedDocument) -> ProfileName:
    """Detect the extraction profile using heuristics (synchronous, zero-cost)."""
    return _detect_heuristic(parsed).profile


class _LLMProfileResult(BaseModel):
    """LLM output for profile classification."""

    document_type: str = "general"
    reasoning: str = ""


async def detect_profile_with_llm(
    parsed: ParsedDocument, settings: Settings
) -> ProfileName:
    """Detect profile using heuristics first, LLM fallback for low-confidence cases.

    Enabled by ``settings.profile_llm_fallback``. Falls back to pure heuristic
    if the LLM call fails or is disabled.
    """
    result = _detect_heuristic(parsed)

    if result.confidence == "high":
        return result.profile

    # LLM fallback for ambiguous documents
    if not getattr(settings, "profile_llm_fallback", False):
        return result.profile

    logger.info("Low-confidence profile detection, using LLM fallback...")

    try:
        from ingestible.pipeline.stage4_enrichment import _make_client

        client = _make_client(settings)
        sample = parsed.full_markdown[:2000] if hasattr(parsed, "full_markdown") else ""
        title = parsed.title or ""

        prompt = f"""Classify this document into one of these types: paper, article, documentation, general.

TITLE: {title}
CONTENT (first 2000 chars):
{sample}

Respond with JSON:
- document_type: one of "paper", "article", "documentation", "general"
- reasoning: one sentence explaining your choice"""

        llm_result = await client.generate_json(prompt, _LLMProfileResult)
        detected = llm_result.document_type.lower().strip()

        if detected in PROFILES:
            logger.info(
                "LLM profile detection: %s (reason: %s)", detected, llm_result.reasoning
            )
            return detected  # type: ignore[return-value]

        logger.warning("LLM returned unknown profile '%s', using heuristic result", detected)
    except Exception as e:
        logger.warning("LLM profile detection failed, using heuristic: %s", e)

    return result.profile
