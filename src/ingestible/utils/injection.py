"""Prompt injection detection and output validation utilities.

Two defences:
- scan_for_injection: pre-LLM call, flags suspicious patterns in raw document text
- validate_enrichment_fields: post-LLM call, flags anomalous field values that may
  indicate a successful injection corrupted structured output
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pre-ingestion pattern scanner
# ---------------------------------------------------------------------------

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "role_override",
        re.compile(
            r"\b(ignore|disregard|forget|override)\b.{0,40}"
            r"\b(instructions?|above|previous|prior|system|prompt)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "role_assumption",
        re.compile(
            r"\b(you are now|you will now|act as|pretend (you are|to be)|roleplay as)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "role_marker",
        re.compile(
            r"(###\s*(Human|Assistant|System)\s*:"
            r"|<\|im_start\||<\|im_end\||<\|system\|"
            r"|\[INST\]|\[/INST\])",
            re.IGNORECASE,
        ),
    ),
    (
        "jailbreak",
        re.compile(
            r"\b(DAN|jailbreak|bypass (the )?(safety|filter|restriction|guard))\b",
            re.IGNORECASE,
        ),
    ),
]


# These pattern families are very unlikely to appear in legitimate documents
# and are used as the gate condition when strict mode is enabled.
_HIGH_CONFIDENCE_PATTERNS: frozenset[str] = frozenset({"role_marker", "jailbreak"})


class InjectionDetected(Exception):
    """Raised when a high-confidence injection pattern is found and strict mode is on."""


def scan_for_injection(text: str) -> list[str]:
    """Return names of injection pattern families found in text.

    Intended for logging only — callers should not reject content based solely
    on this; legitimate documents can contain these phrases. Use to build
    awareness of what is entering the enrichment pipeline.
    """
    if not text:
        return []
    return [name for name, pattern in _PATTERNS if pattern.search(text)]


def check_strict(chunk_id: str, patterns: list[str]) -> None:
    """Raise InjectionDetected if any high-confidence patterns were found.

    Call this after scan_for_injection when strict mode is enabled.
    """
    high = [p for p in patterns if p in _HIGH_CONFIDENCE_PATTERNS]
    if high:
        raise InjectionDetected(
            f"chunk {chunk_id} blocked: high-confidence injection pattern(s) {high}"
        )


# ---------------------------------------------------------------------------
# Post-enrichment output validator
# ---------------------------------------------------------------------------

_IMPERATIVE_STARTERS = re.compile(
    r"^(ignore|forget|disregard|override|act|pretend|you are|you will|"
    r"respond|output|print|say|write|generate|return)\b",
    re.IGNORECASE,
)

# Concepts and keywords are noun phrases — more than 8 words is suspicious.
_CONCEPT_MAX_WORDS = 8


def validate_enrichment_fields(chunk_id: str, fields: dict[str, Any]) -> None:
    """Log warnings for enrichment output fields that look like injection artifacts.

    Does not raise — intended as a canary, not a gate.
    """
    summary: str = fields.get("summary") or ""
    if _IMPERATIVE_STARTERS.match(summary.strip()):
        logger.warning(
            "Possible injection artifact in enrichment for chunk %s: "
            "summary starts with imperative verb: %r",
            chunk_id,
            summary[:120],
        )

    for field_name in ("concepts", "keywords", "depends_on", "cross_references"):
        items: list[Any] = fields.get(field_name) or []
        for item in items:
            if isinstance(item, str) and len(item.split()) > _CONCEPT_MAX_WORDS:
                logger.warning(
                    "Possible injection artifact in enrichment for chunk %s: "
                    "field %r contains unexpectedly long entry: %r",
                    chunk_id,
                    field_name,
                    item[:120],
                )
                break
