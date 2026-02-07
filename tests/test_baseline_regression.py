"""Baseline regression test — compares current metrics against v0.7.2 baseline.

Fails if chunk counts change or performance degrades beyond tolerance.

Run with:  pytest tests/test_baseline_regression.py -v -s
"""

from __future__ import annotations

import json
import time
from collections import defaultdict
from pathlib import Path

from ingestion_tool.config import Settings
from ingestion_tool.models.document import DocumentStructure, StructureNode
from ingestion_tool.pipeline.stage3_chunking import chunk_document
from ingestion_tool.pipeline.stage6_storage import load_chunks, save_document
from ingestion_tool.search.bm25_store import BM25Store
from ingestion_tool.search.concept_index import ConceptIndex
from ingestion_tool.utils.text import split_paragraphs
from ingestion_tool.utils.tokens import count_tokens

BASELINE_PATH = Path(__file__).parent / "baseline_v0.7.2.json"


def _load_baseline() -> dict:
    return json.loads(BASELINE_PATH.read_text())


def _build_baseline_document() -> DocumentStructure:
    """Reproduce the exact same document used to generate the baseline."""
    paragraph = (
        "Autonomous agents leverage tool-use capabilities to interact with external "
        "systems. The Model Context Protocol standardises how hosts, clients and "
        "servers communicate over JSON-RPC transports. Each tool invocation is a "
        "structured request-response cycle carrying typed parameters and results."
    )

    def make_structure(n_ch, n_sec, n_para):
        section_body = "\n\n".join([paragraph] * n_para)
        chapters = []
        for ci in range(n_ch):
            sections = []
            for si in range(n_sec):
                sections.append(StructureNode(
                    id=f"ch{ci}-sec{si}", title=f"Section {ci}.{si}", level=2,
                    content=section_body, page_start=ci * 10 + si, page_end=ci * 10 + si + 1,
                ))
            chapters.append(StructureNode(
                id=f"ch{ci}", title=f"Chapter {ci}", level=1,
                page_start=ci * 10, page_end=ci * 10 + n_sec, children=sections,
            ))
        root = StructureNode(
            id="root", title="Baseline Doc", level=0,
            page_end=n_ch * 10, children=chapters,
        )
        return DocumentStructure(doc_id="baseline-doc", title="Baseline Doc", root=root)

    b = _load_baseline()["test_document"]
    return make_structure(b["chapters"], b["sections_per_chapter"], b["paragraphs_per_section"])


# ---------------------------------------------------------------------------
# Regression: chunk counts must be identical
# ---------------------------------------------------------------------------

def test_chunk_counts_match_baseline(tmp_path):
    """Chunk counts must exactly match the baseline — any drift means the algorithm changed."""
    baseline = _load_baseline()
    settings = Settings(data_dir=tmp_path, max_chunk_tokens=500, min_chunk_tokens=100)
    structure = _build_baseline_document()
    chunks = chunk_document(structure, settings)

    b = baseline["chunking"]
    assert len(chunks.l1_chunks) == b["l1_chapters"], (
        f"L1 count changed: {len(chunks.l1_chunks)} vs baseline {b['l1_chapters']}"
    )
    assert len(chunks.l2_chunks) == b["l2_sections"], (
        f"L2 count changed: {len(chunks.l2_chunks)} vs baseline {b['l2_sections']}"
    )
    assert len(chunks.l3_chunks) == b["l3_passages"], (
        f"L3 count changed: {len(chunks.l3_chunks)} vs baseline {b['l3_passages']}"
    )


# ---------------------------------------------------------------------------
# Regression: total token output must be stable
# ---------------------------------------------------------------------------

def test_token_output_matches_baseline(tmp_path):
    """Total L3 token count must not drift — protects against silent content changes."""
    baseline = _load_baseline()
    settings = Settings(data_dir=tmp_path, max_chunk_tokens=500, min_chunk_tokens=100)
    structure = _build_baseline_document()
    chunks = chunk_document(structure, settings)

    total_tokens = sum(count_tokens(c.content) for c in chunks.l3_chunks)
    expected = baseline["chunking"]["total_l3_tokens"]

    assert total_tokens == expected, (
        f"Total L3 tokens changed: {total_tokens} vs baseline {expected}"
    )


# ---------------------------------------------------------------------------
# Regression: chunk size distribution must stay within bounds
# ---------------------------------------------------------------------------

def test_chunk_sizes_within_baseline(tmp_path):
    """Min/max/mean token counts should stay close to baseline values."""
    baseline = _load_baseline()
    settings = Settings(data_dir=tmp_path, max_chunk_tokens=500, min_chunk_tokens=100)
    structure = _build_baseline_document()
    chunks = chunk_document(structure, settings)

    sizes = sorted(count_tokens(c.content) for c in chunks.l3_chunks)
    b = baseline["chunking"]

    assert sizes[0] == b["l3_token_min"], (
        f"Min chunk size changed: {sizes[0]} vs baseline {b['l3_token_min']}"
    )
    assert sizes[-1] == b["l3_token_max"], (
        f"Max chunk size changed: {sizes[-1]} vs baseline {b['l3_token_max']}"
    )
    mean = round(sum(sizes) / len(sizes))
    assert mean == b["l3_token_mean"], (
        f"Mean chunk size changed: {mean} vs baseline {b['l3_token_mean']}"
    )


# ---------------------------------------------------------------------------
# Regression: storage round-trip preserves all data
# ---------------------------------------------------------------------------

def test_storage_roundtrip_preserves_baseline(tmp_path):
    """Save + load must produce identical chunk counts and content."""
    baseline = _load_baseline()
    settings = Settings(data_dir=tmp_path, max_chunk_tokens=500, min_chunk_tokens=100)
    structure = _build_baseline_document()
    chunks = chunk_document(structure, settings)

    doc_dir = save_document(structure, chunks, settings)
    loaded = load_chunks(doc_dir)

    assert len(loaded.l1_chunks) == baseline["chunking"]["l1_chapters"]
    assert len(loaded.l2_chunks) == baseline["chunking"]["l2_sections"]
    assert len(loaded.l3_chunks) == baseline["chunking"]["l3_passages"]

    for orig, reloaded in zip(
        sorted(chunks.l3_chunks, key=lambda c: c.chunk_id),
        sorted(loaded.l3_chunks, key=lambda c: c.chunk_id),
    ):
        assert reloaded.content == orig.content


# ---------------------------------------------------------------------------
# Regression: performance must not degrade beyond 3x baseline
# ---------------------------------------------------------------------------

def test_chunking_performance_regression(tmp_path):
    """Chunking must not be more than 3x slower than baseline (generous for CI variance)."""
    baseline = _load_baseline()
    settings = Settings(data_dir=tmp_path, max_chunk_tokens=500, min_chunk_tokens=100)
    structure = _build_baseline_document()

    runs = []
    for _ in range(5):
        t0 = time.perf_counter()
        chunk_document(structure, settings)
        runs.append(time.perf_counter() - t0)
    median = sorted(runs)[2]

    threshold = baseline["chunking"]["median_time_s"] * 3
    print(f"\n--- Chunking Performance ---")
    print(f"  Baseline: {baseline['chunking']['median_time_s']:.4f}s")
    print(f"  Current:  {median:.4f}s")
    print(f"  Threshold (3x): {threshold:.4f}s")

    assert median < threshold, (
        f"Chunking regressed: {median:.4f}s vs baseline {baseline['chunking']['median_time_s']:.4f}s "
        f"(>{threshold:.4f}s threshold)"
    )


def test_storage_performance_regression(tmp_path):
    """Save/load must not be more than 3x slower than baseline."""
    baseline = _load_baseline()
    settings = Settings(data_dir=tmp_path, max_chunk_tokens=500, min_chunk_tokens=100)
    structure = _build_baseline_document()
    chunks = chunk_document(structure, settings)

    save_runs = []
    load_runs = []
    for _ in range(5):
        s = Settings(data_dir=Path(tmp_path / f"run{len(save_runs)}"), max_chunk_tokens=500, min_chunk_tokens=100)
        t0 = time.perf_counter()
        doc_dir = save_document(structure, chunks, s)
        save_runs.append(time.perf_counter() - t0)
        t0 = time.perf_counter()
        load_chunks(doc_dir)
        load_runs.append(time.perf_counter() - t0)

    save_median = sorted(save_runs)[2]
    load_median = sorted(load_runs)[2]

    save_threshold = baseline["storage_roundtrip"]["save_median_s"] * 3
    load_threshold = baseline["storage_roundtrip"]["load_median_s"] * 3

    print(f"\n--- Storage Performance ---")
    print(f"  Save: {save_median:.4f}s (baseline {baseline['storage_roundtrip']['save_median_s']:.4f}s, threshold {save_threshold:.4f}s)")
    print(f"  Load: {load_median:.4f}s (baseline {baseline['storage_roundtrip']['load_median_s']:.4f}s, threshold {load_threshold:.4f}s)")

    assert save_median < save_threshold, f"Save regressed: {save_median:.4f}s vs threshold {save_threshold:.4f}s"
    assert load_median < load_threshold, f"Load regressed: {load_median:.4f}s vs threshold {load_threshold:.4f}s"


# ---------------------------------------------------------------------------
# Regression: content coverage ratio must stay within ±5%
# ---------------------------------------------------------------------------

def test_content_coverage_regression(tmp_path):
    """Coverage ratio must not drift beyond ±5% of baseline."""
    baseline = _load_baseline()
    settings = Settings(data_dir=tmp_path, max_chunk_tokens=500, min_chunk_tokens=100)
    structure = _build_baseline_document()
    chunks = chunk_document(structure, settings)

    input_chars = sum(
        len(node.content)
        for node in structure.root.walk()
        if node.content and node.level >= 2
    )
    output_chars = sum(len(c.content) for c in chunks.l3_chunks)
    ratio = output_chars / input_chars if input_chars else 0.0

    expected = baseline["content_coverage"]["coverage_ratio"]
    tolerance = 0.05

    print(f"\n--- Content Coverage Regression ---")
    print(f"  Baseline ratio: {expected:.4f}")
    print(f"  Current ratio:  {ratio:.4f}")
    print(f"  Tolerance:      ±{tolerance}")

    assert abs(ratio - expected) <= tolerance, (
        f"Coverage ratio drifted: {ratio:.4f} vs baseline {expected:.4f} (±{tolerance})"
    )


# ---------------------------------------------------------------------------
# Regression: hierarchy orphan counts must not increase
# ---------------------------------------------------------------------------

def test_hierarchy_linkage_regression(tmp_path):
    """Orphan counts must not increase from baseline."""
    baseline = _load_baseline()
    settings = Settings(data_dir=tmp_path, max_chunk_tokens=500, min_chunk_tokens=100)
    structure = _build_baseline_document()
    chunks = chunk_document(structure, settings)

    l2_ids = {c.chunk_id for c in chunks.l2_chunks}
    l1_ids = {c.chunk_id for c in chunks.l1_chunks}

    l3_orphans = sum(1 for c in chunks.l3_chunks if c.parent_section_id not in l2_ids)
    l2_orphans = sum(1 for c in chunks.l2_chunks if c.parent_chapter_id not in l1_ids)

    b = baseline["hierarchy_linkage"]

    print(f"\n--- Hierarchy Linkage Regression ---")
    print(f"  L3 orphans: {l3_orphans} (baseline {b['l3_orphan_count']})")
    print(f"  L2 orphans: {l2_orphans} (baseline {b['l2_orphan_count']})")

    assert l3_orphans <= b["l3_orphan_count"], (
        f"L3 orphan count increased: {l3_orphans} vs baseline {b['l3_orphan_count']}"
    )
    assert l2_orphans <= b["l2_orphan_count"], (
        f"L2 orphan count increased: {l2_orphans} vs baseline {b['l2_orphan_count']}"
    )


# ---------------------------------------------------------------------------
# Regression: disk footprint must stay within ±20%
# ---------------------------------------------------------------------------

def test_disk_footprint_regression(tmp_path):
    """Disk footprint must not grow or shrink beyond ±20% of baseline."""
    baseline = _load_baseline()
    settings = Settings(data_dir=tmp_path, max_chunk_tokens=500, min_chunk_tokens=100)
    structure = _build_baseline_document()
    chunks = chunk_document(structure, settings)
    doc_dir = save_document(structure, chunks, settings)

    total_bytes = 0
    file_count = 0
    for f in doc_dir.rglob("*"):
        if f.is_file():
            total_bytes += f.stat().st_size
            file_count += 1

    b = baseline["disk_footprint"]
    tolerance = 0.20

    print(f"\n--- Disk Footprint Regression ---")
    print(f"  Bytes:  {total_bytes:,} (baseline {b['total_bytes']:,}, ±{tolerance:.0%})")
    print(f"  Files:  {file_count} (baseline {b['file_count']})")

    assert abs(total_bytes - b["total_bytes"]) / b["total_bytes"] <= tolerance, (
        f"Disk footprint drifted: {total_bytes} bytes vs baseline {b['total_bytes']} (±{tolerance:.0%})"
    )
    assert file_count == b["file_count"], (
        f"File count changed: {file_count} vs baseline {b['file_count']}"
    )


# ---------------------------------------------------------------------------
# Regression: search index counts must match exactly
# ---------------------------------------------------------------------------

def test_search_index_counts_regression(tmp_path):
    """BM25 and ConceptIndex counts must exactly match baseline."""
    baseline = _load_baseline()
    settings = Settings(data_dir=tmp_path, max_chunk_tokens=500, min_chunk_tokens=100)
    structure = _build_baseline_document()
    chunks = chunk_document(structure, settings)

    bm25 = BM25Store()
    bm25.add_documents(
        [c.chunk_id for c in chunks.l3_chunks],
        [c.content for c in chunks.l3_chunks],
    )
    bm25.build()

    concept_idx = ConceptIndex()
    for c in chunks.l3_chunks:
        words = set(c.content.lower().split())
        concepts = [w for w in words if len(w) >= 6]
        concept_idx.add_many(concepts, c.chunk_id)

    b = baseline["search_index_counts"]

    print(f"\n--- Search Index Counts Regression ---")
    print(f"  BM25 docs:       {bm25.count} (baseline {b['bm25_doc_count']})")
    print(f"  Concept terms:   {concept_idx.count} (baseline {b['concept_index_term_count']})")

    assert bm25.count == b["bm25_doc_count"], (
        f"BM25 doc count changed: {bm25.count} vs baseline {b['bm25_doc_count']}"
    )
    assert concept_idx.count == b["concept_index_term_count"], (
        f"Concept index term count changed: {concept_idx.count} vs baseline {b['concept_index_term_count']}"
    )


# ---------------------------------------------------------------------------
# Regression: overlap rate must stay stable
# ---------------------------------------------------------------------------

def test_overlap_verification_regression(tmp_path):
    """Overlap metrics must match baseline exactly."""
    baseline = _load_baseline()
    settings = Settings(data_dir=tmp_path, max_chunk_tokens=500, min_chunk_tokens=100)
    structure = _build_baseline_document()
    chunks = chunk_document(structure, settings)

    section_chunks: dict[str, list] = defaultdict(list)
    for c in chunks.l3_chunks:
        section_chunks[c.parent_section_id].append(c)

    overlap_pairs_total = 0
    overlap_pairs_with_shared_content = 0

    for sec_id, sec_chunks in section_chunks.items():
        for i in range(len(sec_chunks) - 1):
            overlap_pairs_total += 1
            paras_n = split_paragraphs(sec_chunks[i].content)
            if paras_n:
                last_para = paras_n[-1]
                if last_para in sec_chunks[i + 1].content:
                    overlap_pairs_with_shared_content += 1

    b = baseline["overlap_verification"]

    print(f"\n--- Overlap Verification Regression ---")
    print(f"  Pairs total:     {overlap_pairs_total} (baseline {b['overlap_pairs_total']})")
    print(f"  Pairs w/ overlap: {overlap_pairs_with_shared_content} (baseline {b['overlap_pairs_with_shared_content']})")

    assert overlap_pairs_total == b["overlap_pairs_total"], (
        f"Overlap pairs total changed: {overlap_pairs_total} vs baseline {b['overlap_pairs_total']}"
    )
    assert overlap_pairs_with_shared_content == b["overlap_pairs_with_shared_content"], (
        f"Overlap pairs with shared content changed: {overlap_pairs_with_shared_content} "
        f"vs baseline {b['overlap_pairs_with_shared_content']}"
    )
