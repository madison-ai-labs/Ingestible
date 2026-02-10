from __future__ import annotations

import re


def split_paragraphs(text: str) -> list[str]:
    """Split text into paragraphs on blank lines, preserving non-empty blocks."""
    parts = re.split(r"\n\s*\n", text)
    return [p.strip() for p in parts if p.strip()]


def split_sentences(text: str) -> list[str]:
    """Split text into sentences. Handles common abbreviations."""
    # Split on sentence-ending punctuation followed by space + uppercase, or newline
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z])", text)
    return [s.strip() for s in parts if s.strip()]


def is_table_block(text: str) -> bool:
    """Detect if a paragraph is a markdown table."""
    lines = text.strip().split("\n")
    if len(lines) < 2:
        return False
    pipe_lines = sum(1 for line in lines if "|" in line)
    return pipe_lines >= len(lines) * 0.6


def is_code_block(text: str) -> bool:
    """Detect if a paragraph is a fenced code block."""
    stripped = text.strip()
    return stripped.startswith("```") and stripped.endswith("```")


def extract_heading_level(line: str) -> int | None:
    """Return the heading level (1-6) from a markdown heading line, or None."""
    m = re.match(r"^(#{1,6})\s+", line)
    return len(m.group(1)) if m else None
