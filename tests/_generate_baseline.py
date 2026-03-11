#!/usr/bin/env python3
"""Generate / update baseline_v0.9.0.json with all metrics.

Run:  python tests/_generate_baseline.py
"""

from __future__ import annotations

import json
import statistics
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np

# Ensure the package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ingestible.config import Settings
from ingestible.models.document import DocumentStructure, StructureNode
from ingestible.pipeline.stage1_parsing import parse_document, SUPPORTED_FORMATS
from ingestible.pipeline.stage3_chunking import chunk_document
from ingestible.pipeline.stage6_storage import load_chunks, save_document
from ingestible.search.bm25_store import BM25Store
from ingestible.search.concept_index import ConceptIndex
from ingestible.utils.text import split_paragraphs
from ingestible.utils.tokens import count_tokens

BASELINE_PATH = Path(__file__).parent / "baseline_v0.9.0.json"


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


def compute_chunking_metrics(structure, settings) -> tuple[dict, object]:
    """Compute chunking counts, token stats, and timing."""
    # Warm up
    chunk_document(structure, settings)

    runs = []
    for _ in range(7):
        t0 = time.perf_counter()
        chunks = chunk_document(structure, settings)
        runs.append(time.perf_counter() - t0)
    median_time = statistics.median(runs)

    total_input_chars = sum(
        len(node.content) for node in structure.root.walk() if node.content
    )
    sizes = sorted(count_tokens(c.content) for c in chunks.l3_chunks)
    total_tokens = sum(sizes)

    return {
        "l1_chapters": len(chunks.l1_chunks),
        "l2_sections": len(chunks.l2_chunks),
        "l3_passages": len(chunks.l3_chunks),
        "total_l3_tokens": total_tokens,
        "l3_token_min": sizes[0] if sizes else 0,
        "l3_token_max": sizes[-1] if sizes else 0,
        "l3_token_median": sizes[len(sizes) // 2] if sizes else 0,
        "l3_token_mean": round(total_tokens / len(sizes)) if sizes else 0,
        "median_time_s": round(median_time, 4),
        "throughput_chars_per_s": round(total_input_chars / max(median_time, 0.0001)),
    }, chunks


def compute_token_counting_metrics() -> dict:
    """Benchmark tiktoken encoding speed."""
    text = "The quick brown fox jumps over the lazy dog. " * 500
    n_iters = 50

    # Warm up
    count_tokens(text)

    runs = []
    for _ in range(n_iters):
        t0 = time.perf_counter()
        count_tokens(text)
        runs.append(time.perf_counter() - t0)

    tokens = count_tokens(text)
    median_ms = statistics.median(runs) * 1000

    return {
        "text_chars": len(text),
        "token_count": tokens,
        "median_per_call_ms": round(median_ms, 2),
    }


def compute_storage_metrics(structure, chunks, tmp_dir) -> dict:
    """Benchmark save/load speed."""
    runs_save = []
    runs_load = []
    for i in range(7):
        s = Settings(data_dir=Path(tmp_dir) / f"run{i}", max_chunk_tokens=500, min_chunk_tokens=100)
        t0 = time.perf_counter()
        doc_dir = save_document(structure, chunks, s)
        runs_save.append(time.perf_counter() - t0)
        t0 = time.perf_counter()
        load_chunks(doc_dir)
        runs_load.append(time.perf_counter() - t0)

    return {
        "save_median_s": round(statistics.median(runs_save), 4),
        "load_median_s": round(statistics.median(runs_load), 4),
    }


def compute_multiformat_parsing(tmp_dir: str) -> dict:
    """Benchmark multi-format parsing — creates sample files and measures output."""
    from docx import Document as DocxDocument

    tmp = Path(tmp_dir)

    # --- Build sample files with known content ---
    sample_md = tmp / "sample.md"
    sample_md.write_text(
        "# Machine Learning Primer\n\n"
        "## Supervised Learning\n\n"
        "Supervised learning trains models on labeled data.\n\n"
        "## Unsupervised Learning\n\n"
        "Unsupervised learning finds patterns without labels.\n\n"
        "| Method | Type |\n| --- | --- |\n| K-means | Clustering |\n| PCA | Reduction |\n"
    )

    sample_txt = tmp / "sample.txt"
    sample_txt.write_text(
        "Introduction to Neural Networks\n\n"
        "Neural networks are computing systems inspired by biological neural networks.\n"
        "They consist of layers of interconnected nodes called neurons.\n\n"
        "Deep learning uses multiple layers to progressively extract features.\n"
    )

    sample_html = tmp / "sample.html"
    sample_html.write_text(
        "<html><body>"
        "<h1>Web Standards Guide</h1>"
        "<h2>HTML5</h2>"
        "<p>HTML5 introduced semantic elements like article, section, and nav.</p>"
        "<h2>CSS3</h2>"
        "<p>CSS3 added animations, flexbox, and grid layout.</p>"
        "<table><tr><th>Feature</th><th>Support</th></tr>"
        "<tr><td>Flexbox</td><td>98%</td></tr></table>"
        "<script>alert('ignored')</script>"
        "</body></html>"
    )

    sample_docx = tmp / "sample.docx"
    doc = DocxDocument()
    doc.add_heading("API Design Handbook", level=1)
    doc.add_heading("REST Principles", level=2)
    doc.add_paragraph("REST APIs use HTTP methods to perform CRUD operations.")
    doc.add_heading("GraphQL", level=2)
    doc.add_paragraph("GraphQL provides a single endpoint with flexible querying.")
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Protocol"
    table.cell(0, 1).text = "Format"
    table.cell(1, 0).text = "REST"
    table.cell(1, 1).text = "JSON"
    doc.save(str(sample_docx))

    # --- Parse each and collect metrics ---
    results = {}
    for path in [sample_md, sample_txt, sample_html, sample_docx]:
        ext = path.suffix.lstrip(".")
        t0 = time.perf_counter()
        parsed = parse_document(path)
        elapsed = time.perf_counter() - t0

        content = parsed.full_markdown
        results[ext] = {
            "title_detected": parsed.title,
            "source_format": parsed.source_format,
            "toc_entries": len(parsed.toc),
            "content_chars": len(content),
            "content_tokens": count_tokens(content) if content else 0,
            "has_table": "|" in content,
            "parse_time_s": round(elapsed, 4),
        }

    return {
        "supported_formats": sorted(SUPPORTED_FORMATS),
        "formats_tested": sorted(results.keys()),
        "results": results,
    }


def compute_semantic_chunking(structure: DocumentStructure, tmp_dir: str) -> dict:
    """Benchmark semantic chunking with a deterministic mock embedder.

    Uses seeded random vectors grouped by topic so that semantic breaks
    are reproducible across runs.
    """
    # Build a multi-topic document large enough to force real splits.
    # Each topic has ~6 sentences so total is ~18 sentences, well over max_chunk_tokens=200.
    topic_a_sents = [
        "Machine learning algorithms learn patterns from large volumes of training data.",
        "Supervised learning requires labeled examples for effective model training.",
        "Neural networks use backpropagation to adjust connection weights across layers.",
        "Gradient descent optimizes the loss function by iteratively updating parameters.",
        "Regularization techniques like dropout prevent overfitting on the training set.",
        "Transfer learning reuses pretrained model weights for new downstream tasks.",
    ]
    topic_b_sents = [
        "The ocean covers approximately seventy percent of the earth's total surface area.",
        "Marine ecosystems support incredible biodiversity especially in tropical coral reefs.",
        "Deep sea hydrothermal vents host chemosynthetic organisms that thrive without sunlight.",
        "Ocean currents distribute heat globally and regulate regional climate patterns.",
        "Phytoplankton produce roughly half of the oxygen in the earth's atmosphere.",
        "Overfishing threatens marine food chains and collapses commercially important fish stocks.",
    ]
    topic_c_sents = [
        "Ancient Roman architecture pioneered the use of arches and concrete construction techniques.",
        "The Colosseum could seat fifty thousand spectators for gladiatorial combat events.",
        "Roman aqueducts transported fresh water across vast distances using gravity alone.",
        "The Pantheon's unreinforced concrete dome remains the largest of its kind today.",
        "Roman roads connected provinces across three continents enabling trade and military movement.",
        "Public baths served as social gathering places central to daily Roman civic life.",
    ]
    mixed_content = (
        " ".join(topic_a_sents) + "\n\n"
        + " ".join(topic_b_sents) + "\n\n"
        + " ".join(topic_c_sents)
    )

    sec_a = StructureNode(id="sec-topics", title="Mixed Topics", level=2, content=mixed_content)
    ch = StructureNode(id="ch1", title="Chapter 1", level=1, page_start=1, page_end=3, children=[sec_a])
    root = StructureNode(id="root", title="Multi-Topic Doc", level=0, page_end=3, children=[ch])
    semantic_structure = DocumentStructure(doc_id="semantic-baseline", title="Multi-Topic Doc", root=root)

    # Deterministic mock embedder: 3 clusters of vectors
    rng = np.random.RandomState(42)
    dim = 64

    # Cluster centers
    center_a = rng.randn(dim)
    center_a /= np.linalg.norm(center_a)
    center_b = rng.randn(dim)
    center_b /= np.linalg.norm(center_b)
    center_c = rng.randn(dim)
    center_c /= np.linalg.norm(center_c)

    def mock_embed(texts):
        """Return vectors clustered by topic keywords."""
        vectors = []
        for text in texts:
            t_lower = text.lower()
            if any(w in t_lower for w in ["learning", "neural", "training", "algorithm", "backpropagation", "supervised"]):
                base = center_a
            elif any(w in t_lower for w in ["ocean", "marine", "reef", "trench", "sea", "biodiversity"]):
                base = center_b
            elif any(w in t_lower for w in ["roman", "colosseum", "arch", "aqueduct", "gladiator", "concrete"]):
                base = center_c
            else:
                base = rng.randn(dim)
            # Add small noise for realism
            v = base + rng.randn(dim) * 0.05
            v /= np.linalg.norm(v)
            vectors.append(v.tolist())
        return vectors

    embedder = MagicMock()
    embedder.embed_passages.side_effect = mock_embed

    settings_semantic = Settings(
        data_dir=Path(tmp_dir) / "semantic",
        chunking_strategy="semantic",
        max_chunk_tokens=120,
        min_chunk_tokens=30,
        semantic_threshold_percentile=25,
    )
    settings_paragraph = Settings(
        data_dir=Path(tmp_dir) / "paragraph",
        chunking_strategy="paragraph",
        max_chunk_tokens=120,
        min_chunk_tokens=30,
    )

    # Run semantic chunking
    t0 = time.perf_counter()
    sem_chunks = chunk_document(semantic_structure, settings_semantic, embedder=embedder)
    sem_time = time.perf_counter() - t0

    # Run paragraph chunking on same content for comparison
    t0 = time.perf_counter()
    para_chunks = chunk_document(semantic_structure, settings_paragraph)
    para_time = time.perf_counter() - t0

    sem_sizes = sorted(count_tokens(c.content) for c in sem_chunks.l3_chunks)
    para_sizes = sorted(count_tokens(c.content) for c in para_chunks.l3_chunks)

    return {
        "input_topics": 3,
        "input_chars": len(mixed_content),
        "input_tokens": count_tokens(mixed_content),
        "semantic": {
            "l3_passages": len(sem_chunks.l3_chunks),
            "total_tokens": sum(sem_sizes),
            "token_min": sem_sizes[0] if sem_sizes else 0,
            "token_max": sem_sizes[-1] if sem_sizes else 0,
            "token_mean": round(sum(sem_sizes) / len(sem_sizes)) if sem_sizes else 0,
            "time_s": round(sem_time, 4),
        },
        "paragraph": {
            "l3_passages": len(para_chunks.l3_chunks),
            "total_tokens": sum(para_sizes),
            "token_min": para_sizes[0] if para_sizes else 0,
            "token_max": para_sizes[-1] if para_sizes else 0,
            "token_mean": round(sum(para_sizes) / len(para_sizes)) if para_sizes else 0,
            "time_s": round(para_time, 4),
        },
    }


def main():
    baseline = json.loads(BASELINE_PATH.read_text())

    with tempfile.TemporaryDirectory() as tmp:
        settings = Settings(data_dir=Path(tmp), max_chunk_tokens=500, min_chunk_tokens=100)
        structure = _build_baseline_document(baseline)

        # Chunking metrics (includes timing)
        chunking, chunks = compute_chunking_metrics(structure, settings)

        # Token counting benchmark
        token_counting = compute_token_counting_metrics()

        # Storage benchmark
        storage_roundtrip = compute_storage_metrics(structure, chunks, tmp)

        # Re-save for disk footprint measurement
        doc_dir = save_document(structure, chunks, settings)

        # Compute remaining metrics
        coverage = compute_content_coverage(structure, chunks)
        linkage = compute_hierarchy_linkage(chunks)
        footprint = compute_disk_footprint(doc_dir)
        index_counts = compute_search_index_counts(chunks)
        overlap = compute_overlap_verification(chunks)

        # v0.8.0 features
        multiformat = compute_multiformat_parsing(tmp)
        semantic = compute_semantic_chunking(structure, tmp)

    # Update baseline
    baseline["chunking"] = chunking
    baseline["token_counting"] = token_counting
    baseline["storage_roundtrip"] = storage_roundtrip
    baseline["content_coverage"] = coverage
    baseline["hierarchy_linkage"] = linkage
    baseline["disk_footprint"] = footprint
    baseline["search_index_counts"] = index_counts
    baseline["overlap_verification"] = overlap
    baseline["multiformat_parsing"] = multiformat
    baseline["semantic_chunking"] = semantic

    BASELINE_PATH.write_text(json.dumps(baseline, indent=2) + "\n")
    print("Updated baseline_v0.9.0.json:")
    print(json.dumps(baseline, indent=2))


if __name__ == "__main__":
    main()
