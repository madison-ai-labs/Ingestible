"""Stage 1c — Content-Tier Classification.

Assigns each content block a tier that controls downstream behavior:
  T0 — Verbatim: code, formulas, configs, regex, API signatures
  T1 — Structural: JSON, tables, key-value pairs, structured data
  T2 — Extractive: dense factual prose (definitions, specs, procedures)
  T3 — Compressible: narrative prose, discussion, examples

Classification is heuristic-only (no LLM calls). Runs per content block
before chunking, so the tier informs how chunking proceeds.
"""

from __future__ import annotations

import logging
import re

from ingestible.models.document import ParsedDocument

logger = logging.getLogger(__name__)

# --- Heuristic detectors ---

# Code/config patterns
_CODE_FENCE_RE = re.compile(r"^```", re.MULTILINE)
_LATEX_RE = re.compile(
    r"\\(?:begin\{|end\{|frac|sum|int|alpha|beta|gamma|delta|theta|lambda|sigma|partial)"
)
_LEGAL_SECTION_RE = re.compile(r"^§\s*\d+", re.MULTILINE)

# Structural data patterns
_JSON_LIKE_RE = re.compile(r"^\s*[\[{]", re.MULTILINE)
_KEY_VALUE_RE = re.compile(r"^\s*[\w\-]+\s*[:=]\s*.+", re.MULTILINE)

# High-density content signals
_URL_RE = re.compile(r"https?://\S+")
_FILE_PATH_RE = re.compile(r"(?:/[\w.\-]+){2,}|[\w.\-]+(?:\\[\w.\-]+){2,}")
_HEX_RE = re.compile(r"\b(?:0x)?[0-9a-fA-F]{8,}\b")
_REGEX_RE = re.compile(r"(?:\^|\$|\\[dDwWsSbB]|\[[^\]]+\]|\{[\d,]+\})")
_VERSION_RE = re.compile(r"\b\d+\.\d+(?:\.\d+)+\b")


def classify_block(text: str) -> str:
    """Classify a single content block into a tier (T0, T1, T2, T3).

    Heuristic, deterministic, sub-millisecond per block.
    """
    stripped = text.strip()
    lines = stripped.split("\n")
    line_count = len(lines)

    # --- T0: Verbatim (code, formulas, configs) ---

    # Fenced code blocks
    if stripped.startswith("```") and stripped.endswith("```"):
        return "T0"

    # LaTeX formulas
    if stripped.startswith("$$") or stripped.startswith("\\begin{"):
        return "T0"
    if _LATEX_RE.search(stripped) and len(stripped) < 500:
        return "T0"

    # High structural regularity: indentation depth + bracket density
    bracket_count = (
        stripped.count("{") + stripped.count("}") + stripped.count("[") + stripped.count("]")
    )
    bracket_density = bracket_count / max(len(stripped), 1)
    if bracket_density > 0.05 and line_count >= 3:
        # Looks like code or config
        return "T0"

    # Legal citations (§)
    if _LEGAL_SECTION_RE.search(stripped):
        return "T0"

    # Lines with high indentation consistency (code-like)
    if line_count >= 3:
        indented = sum(1 for line in lines if line and line[0] in (" ", "\t"))
        if indented / line_count > 0.7:
            # High pattern density signals
            pattern_hits = (
                len(_URL_RE.findall(stripped))
                + len(_FILE_PATH_RE.findall(stripped))
                + len(_HEX_RE.findall(stripped))
                + len(_REGEX_RE.findall(stripped))
                + len(_VERSION_RE.findall(stripped))
            )
            if pattern_hits >= 3 or bracket_density > 0.03:
                return "T0"

    # --- T1: Structural (tables, JSON, key-value) ---

    # Markdown tables
    pipe_lines = sum(1 for line in lines if "|" in line)
    if line_count >= 2 and pipe_lines >= line_count * 0.6:
        return "T1"

    # JSON-like blocks
    if _JSON_LIKE_RE.match(stripped) and bracket_density > 0.02:
        return "T1"

    # Key-value heavy blocks (YAML-like, env files, etc.)
    kv_lines = len(_KEY_VALUE_RE.findall(stripped))
    if line_count >= 3 and kv_lines / line_count > 0.6:
        return "T1"

    # --- T2 vs T3: extractive vs compressible prose ---

    # T2 signals: high information density
    words = stripped.split()
    word_count = len(words)
    if word_count == 0:
        return "T3"

    # Unique token ratio (high = dense/technical, low = repetitive/narrative)
    unique_ratio = len(set(w.lower() for w in words)) / word_count

    # Numeric density (specs, measurements, data)
    numeric_tokens = sum(1 for w in words if any(c.isdigit() for c in w))
    numeric_ratio = numeric_tokens / word_count

    # Short, dense, factual blocks -> T2
    if unique_ratio > 0.75 and numeric_ratio > 0.1:
        return "T2"

    # Definitions, specs, procedures (short paragraphs with high info density)
    if word_count < 100 and unique_ratio > 0.7:
        return "T2"

    return "T3"


def classify_document(parsed: ParsedDocument) -> dict[str, list[tuple[str, str]]]:
    """Classify all content blocks in a parsed document.

    Returns a dict mapping page_num to list of (block_text, tier) tuples.
    This classification is stored on the ParsedDocument for use by Stage 3.
    """
    result: dict[str, list[tuple[str, str]]] = {}
    total_counts = {"T0": 0, "T1": 0, "T2": 0, "T3": 0}

    for page in parsed.pages:
        # Split page markdown into blocks (paragraphs, code fences, tables)
        blocks = _split_into_blocks(page.markdown)
        classified: list[tuple[str, str]] = []
        for block in blocks:
            tier = classify_block(block)
            classified.append((block, tier))
            total_counts[tier] += 1
        result[str(page.page_num)] = classified

    logger.info(
        "Content classification: T0=%d T1=%d T2=%d T3=%d",
        total_counts["T0"],
        total_counts["T1"],
        total_counts["T2"],
        total_counts["T3"],
    )
    return result


def _split_into_blocks(markdown: str) -> list[str]:
    """Split markdown into content blocks, preserving code fences as single blocks."""
    blocks: list[str] = []
    current: list[str] = []
    in_code_fence = False

    for line in markdown.split("\n"):
        if line.strip().startswith("```"):
            if in_code_fence:
                # End of code fence
                current.append(line)
                blocks.append("\n".join(current))
                current = []
                in_code_fence = False
            else:
                # Flush any accumulated prose
                if current:
                    prose = "\n".join(current).strip()
                    if prose:
                        # Split prose on blank lines into separate blocks
                        for para in re.split(r"\n\s*\n", prose):
                            para = para.strip()
                            if para:
                                blocks.append(para)
                    current = []
                # Start of code fence
                current.append(line)
                in_code_fence = True
        else:
            current.append(line)

    # Flush remainder
    if current:
        text = "\n".join(current).strip()
        if text:
            if in_code_fence:
                # Unclosed code fence — treat as code block anyway
                blocks.append(text)
            else:
                for para in re.split(r"\n\s*\n", text):
                    para = para.strip()
                    if para:
                        blocks.append(para)

    return blocks
