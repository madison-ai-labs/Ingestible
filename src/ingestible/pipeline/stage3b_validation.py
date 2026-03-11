"""Stage 3b — Quality Validation.

Validates chunks after chunking: removes empty L3 chunks, computes token
statistics, and logs a quality report. Warns for very small (<50 tokens)
or very large (>1000 tokens) chunks.
"""

from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass, field

from ingestible.models.chunks import ChunkSet
from ingestible.utils.tokens import count_tokens

logger = logging.getLogger(__name__)


@dataclass
class QualityReport:
    total_l3: int = 0
    removed_empty: int = 0
    below_min: int = 0
    above_max: int = 0
    token_mean: float = 0.0
    token_median: float = 0.0
    token_min: int = 0
    token_max: int = 0


def validate_chunks(chunks: ChunkSet) -> tuple[ChunkSet, QualityReport]:
    """Remove empty L3 chunks, compute stats, return cleaned ChunkSet + report."""
    report = QualityReport()

    original = chunks.l3_chunks
    report.total_l3 = len(original)

    # 1. Remove empty chunks
    kept: list = []
    removed_ids: set[str] = set()
    for c in original:
        if not c.content.strip():
            removed_ids.add(c.chunk_id)
            report.removed_empty += 1
        else:
            kept.append(c)

    # 2. Compute token stats on remaining
    if kept:
        token_counts = [count_tokens(c.content) for c in kept]
        report.token_mean = round(statistics.mean(token_counts), 1)
        report.token_median = round(statistics.median(token_counts), 1)
        report.token_min = min(token_counts)
        report.token_max = max(token_counts)

        for tc in token_counts:
            if tc < 50:
                report.below_min += 1
            if tc > 1000:
                report.above_max += 1

    # 3. Warn for outliers
    if report.below_min:
        logger.warning(
            "Quality: %d chunk(s) below 50 tokens — may have low embedding quality",
            report.below_min,
        )
    if report.above_max:
        logger.warning(
            "Quality: %d chunk(s) above 1000 tokens — consider reducing max_chunk_tokens",
            report.above_max,
        )

    # 4. Update l0.total_passages and l2.children_ids
    l0 = chunks.l0.model_copy(update={"total_passages": len(kept)})

    l2_chunks = []
    for l2 in chunks.l2_chunks:
        new_children = [cid for cid in l2.children_ids if cid not in removed_ids]
        l2_chunks.append(l2.model_copy(update={"children_ids": new_children}))

    # 5. Log report
    logger.info(
        "Validation: %d chunks → %d kept (%d empty removed). "
        "Tokens: mean=%.0f median=%.0f min=%d max=%d",
        report.total_l3,
        len(kept),
        report.removed_empty,
        report.token_mean,
        report.token_median,
        report.token_min,
        report.token_max,
    )

    cleaned = chunks.model_copy(
        update={"l0": l0, "l2_chunks": l2_chunks, "l3_chunks": kept}
    )
    return cleaned, report
