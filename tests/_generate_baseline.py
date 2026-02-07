#!/usr/bin/env python3
"""Generate / update baseline_v0.7.2.json with all metrics.

Run:  python tests/_generate_baseline.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

# Ensure the package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ingestion_tool.config import Settings
from ingestion_tool.models.document import DocumentStructure, StructureNode
from ingestion_tool.pipeline.stage3_chunking import chunk_document
from ingestion_tool.pipeline.stage6_storage import save_document
from ingestion_tool.search.bm25_store import BM25Store
from ingestion_tool.search.concept_index import ConceptIndex
from ingestion_tool.utils.text import split_paragraphs
from ingestion_tool.utils.tokens import count_tokens

BASELINE_PATH = Path(__file__).parent / "baseline_v0.7.2.json"


def _build_baseline_document(baseline: dict) -> DocumentStructure:
    paragraph = (
        "Autonomous agents leverage tool-use capabilities to interact with external "
        "systems. The Model Context Protocol standardises how hosts, clients and "
        "servers communicate over JSON-RPC transports. Each tool invocation is a "
        "structured request-response cycle carrying typed parameters and results."
    )

    b = baseline["test_document"]
    n_ch = b["chapters"]
    n_sec = b["sections_per_chapter"]
    n_para = b["paragraphs_per_section"]
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


def compute_content_coverage(structure: DocumentStructure, chunks) -> dict:
    """Metric 1: content coverage ratio."""
    input_chars = sum(
        len(node.content)
        for node in structure.root.walk()
        if node.content and node.level >= 2  # leaf sections
    )
    output_chars = sum(len(c.content) for c in chunks.l3_chunks)
    ratio = output_chars / input_chars if input_chars else 0.0
    return {
        "input_leaf_chars": input_chars,
        "l3_output_chars": output_chars,
        "coverage_ratio": round(ratio, 4),
    }


def compute_hierarchy_linkage(chunks) -> dict:
    """Metric 2: orphan counts at L3 and L2."""
    l2_ids = {c.chunk_id for c in chunks.l2_chunks}
    l1_ids = {c.chunk_id for c in chunks.l1_chunks}

    l3_orphan_count = sum(
        1 for c in chunks.l3_chunks if c.parent_section_id not in l2_ids
    )
    l2_orphan_count = sum(
        1 for c in chunks.l2_chunks if c.parent_chapter_id not in l1_ids
    )
    return {
        "l3_orphan_count": l3_orphan_count,
        "l2_orphan_count": l2_orphan_count,
    }


def compute_disk_footprint(doc_dir: Path) -> dict:
    """Metric 3: total bytes and file count on disk."""
    total_bytes = 0
    file_count = 0
    for f in doc_dir.rglob("*"):
        if f.is_file():
            total_bytes += f.stat().st_size
            file_count += 1
    return {
        "total_bytes": total_bytes,
        "file_count": file_count,
    }


def compute_search_index_counts(chunks) -> dict:
    """Metric 4: BM25 doc count and concept index term count."""
    # BM25
    bm25 = BM25Store()
    bm25.add_documents(
        [c.chunk_id for c in chunks.l3_chunks],
        [c.content for c in chunks.l3_chunks],
    )
    bm25.build()

    # ConceptIndex — extract simple keyword concepts from each chunk
    concept_idx = ConceptIndex()
    for c in chunks.l3_chunks:
        words = set(c.content.lower().split())
        # Use words >= 6 chars as proxy "concepts" (same logic we'll use in tests)
        concepts = [w for w in words if len(w) >= 6]
        concept_idx.add_many(concepts, c.chunk_id)

    return {
        "bm25_doc_count": bm25.count,
        "concept_index_term_count": concept_idx.count,
    }


def compute_overlap_verification(chunks) -> dict:
    """Metric 5: overlap between consecutive L3 chunks in the same section."""
    # Group L3 chunks by parent_section_id, preserving order
    from collections import defaultdict
    section_chunks: dict[str, list] = defaultdict(list)
    for c in chunks.l3_chunks:
        section_chunks[c.parent_section_id].append(c)

    overlap_pairs_total = 0
    overlap_pairs_with_shared_content = 0

    for sec_id, sec_chunks in section_chunks.items():
        for i in range(len(sec_chunks) - 1):
            overlap_pairs_total += 1
            # Check if last paragraph of chunk N appears in chunk N+1
            paras_n = split_paragraphs(sec_chunks[i].content)
            if paras_n:
                last_para = paras_n[-1]
                if last_para in sec_chunks[i + 1].content:
                    overlap_pairs_with_shared_content += 1

    return {
        "overlap_pairs_total": overlap_pairs_total,
        "overlap_pairs_with_shared_content": overlap_pairs_with_shared_content,
    }


def main():
    baseline = json.loads(BASELINE_PATH.read_text())

    with tempfile.TemporaryDirectory() as tmp:
        settings = Settings(data_dir=Path(tmp), max_chunk_tokens=500, min_chunk_tokens=100)
        structure = _build_baseline_document(baseline)
        chunks = chunk_document(structure, settings)
        doc_dir = save_document(structure, chunks, settings)

        # Compute all new metrics
        coverage = compute_content_coverage(structure, chunks)
        linkage = compute_hierarchy_linkage(chunks)
        footprint = compute_disk_footprint(doc_dir)
        index_counts = compute_search_index_counts(chunks)
        overlap = compute_overlap_verification(chunks)

    # Update baseline
    baseline["content_coverage"] = coverage
    baseline["hierarchy_linkage"] = linkage
    baseline["disk_footprint"] = footprint
    baseline["search_index_counts"] = index_counts
    baseline["overlap_verification"] = overlap

    BASELINE_PATH.write_text(json.dumps(baseline, indent=2) + "\n")
    print("Updated baseline_v0.7.2.json:")
    print(json.dumps(baseline, indent=2))


if __name__ == "__main__":
    main()
