"""Auto-merging retrieval: promote L3 results to their parent L2/L1 when
multiple passages from the same section appear in search results."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from ingestible.models.chunks import ChunkSet, L2Chunk
from ingestible.models.search import SearchResult


@dataclass
class AutoMergeConfig:
    """Configuration for auto-merge behaviour."""

    enabled: bool = False
    merge_threshold: int = 3  # min L3 chunks from same L2 to trigger merge
    prefer_l1: bool = False  # also try merging L2s up to L1 with same threshold


def _l2_to_result(
    l2: L2Chunk,
    score: float,
    match_sources: list[str],
    chunk_set: ChunkSet,
) -> SearchResult:
    """Build a SearchResult from an L2Chunk."""
    # Resolve chapter title from parent L1
    chapter_title = ""
    if l2.parent_chapter_id:
        for l1 in chunk_set.l1_chunks:
            if l1.chunk_id == l2.parent_chapter_id:
                chapter_title = l1.title
                break

    return SearchResult(
        chunk_id=l2.chunk_id,
        content=l2.content,
        summary=l2.section_summary,
        score=score,
        chapter=chapter_title,
        section=l2.title,
        page_start=l2.page_start,
        page_end=l2.page_end,
        match_sources=match_sources,
        doc_id=chunk_set.doc_id,
        doc_title=chunk_set.l0.title,
    )


def _l1_to_result(
    l1_chunk,
    score: float,
    match_sources: list[str],
    chunk_set: ChunkSet,
) -> SearchResult:
    """Build a SearchResult from an L1Chunk."""
    return SearchResult(
        chunk_id=l1_chunk.chunk_id,
        content=l1_chunk.content,
        summary=l1_chunk.chapter_summary,
        score=score,
        chapter=l1_chunk.title,
        section="",
        page_start=l1_chunk.page_start,
        page_end=l1_chunk.page_end,
        match_sources=match_sources,
        doc_id=chunk_set.doc_id,
        doc_title=chunk_set.l0.title,
    )


def _merge_l3_to_l2(
    results: list[SearchResult],
    chunk_set: ChunkSet,
    threshold: int,
) -> list[SearchResult]:
    """Replace clusters of L3 results with their parent L2 where threshold is met."""
    l2_index = {c.chunk_id: c for c in chunk_set.l2_chunks}
    l3_index = {c.chunk_id: c for c in chunk_set.l3_chunks}

    # Identify which results are L3 chunks and group by parent section
    l3_groups: dict[str, list[SearchResult]] = defaultdict(list)
    non_l3: list[SearchResult] = []

    for r in results:
        l3 = l3_index.get(r.chunk_id)
        if l3 and l3.parent_section_id:
            l3_groups[l3.parent_section_id].append(r)
        else:
            non_l3.append(r)

    merged: list[SearchResult] = list(non_l3)

    for parent_id, group in l3_groups.items():
        if len(group) >= threshold and parent_id in l2_index:
            l2 = l2_index[parent_id]
            max_score = max(r.score for r in group)
            # Collect unique match sources from constituents plus the merge marker
            all_sources: set[str] = set()
            for r in group:
                all_sources.update(r.match_sources)
            all_sources.add("auto_merged")
            merged.append(_l2_to_result(l2, max_score, sorted(all_sources), chunk_set))
        else:
            merged.extend(group)

    return merged


def _merge_l2_to_l1(
    results: list[SearchResult],
    chunk_set: ChunkSet,
    threshold: int,
) -> list[SearchResult]:
    """Replace clusters of L2 results with their parent L1 where threshold is met."""
    l1_index = {c.chunk_id: c for c in chunk_set.l1_chunks}
    l2_index = {c.chunk_id: c for c in chunk_set.l2_chunks}

    l2_groups: dict[str, list[SearchResult]] = defaultdict(list)
    non_l2: list[SearchResult] = []

    for r in results:
        l2 = l2_index.get(r.chunk_id)
        if l2 and l2.parent_chapter_id:
            l2_groups[l2.parent_chapter_id].append(r)
        else:
            non_l2.append(r)

    merged: list[SearchResult] = list(non_l2)

    for parent_id, group in l2_groups.items():
        if len(group) >= threshold and parent_id in l1_index:
            l1 = l1_index[parent_id]
            max_score = max(r.score for r in group)
            all_sources: set[str] = set()
            for r in group:
                all_sources.update(r.match_sources)
            all_sources.add("auto_merged")
            merged.append(_l1_to_result(l1, max_score, sorted(all_sources), chunk_set))
        else:
            merged.extend(group)

    return merged


def auto_merge_results(
    results: list[SearchResult],
    chunk_set: ChunkSet,
    config: AutoMergeConfig | None = None,
) -> list[SearchResult]:
    """Apply auto-merging: promote L3 clusters to L2 (and optionally L2 to L1).

    Args:
        results: Search results to merge.
        chunk_set: The document's full chunk hierarchy.
        config: Merge settings. Defaults to a disabled config (pass-through).

    Returns:
        Merged and re-sorted results list.
    """
    if config is None:
        config = AutoMergeConfig()

    if not config.enabled or not results:
        return results

    merged = _merge_l3_to_l2(results, chunk_set, config.merge_threshold)

    if config.prefer_l1:
        merged = _merge_l2_to_l1(merged, chunk_set, config.merge_threshold)

    merged.sort(key=lambda r: r.score, reverse=True)
    return merged
