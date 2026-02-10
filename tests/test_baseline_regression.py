"""Baseline regression test — compares current metrics against v0.8.0 baseline.

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
from ingestion_tool.pipeline.stage1_parsing import parse_document, SUPPORTED_FORMATS
from ingestion_tool.pipeline.stage3_chunking import chunk_document
from ingestion_tool.pipeline.stage6_storage import load_chunks, save_document
from ingestion_tool.search.bm25_store import BM25Store
from ingestion_tool.search.concept_index import ConceptIndex
from ingestion_tool.utils.text import split_paragraphs
from ingestion_tool.utils.tokens import count_tokens

BASELINE_PATH = Path(__file__).parent / "baseline_v0.9.0.json"


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


# ---------------------------------------------------------------------------
# Regression: supported formats must not shrink
# ---------------------------------------------------------------------------

def test_supported_formats_regression():
    """Supported format set must not lose formats from baseline."""
    baseline = _load_baseline()
    b = baseline.get("multiformat_parsing", {})
    if not b:
        return  # no baseline data yet

    baseline_formats = set(b["supported_formats"])
    current_formats = SUPPORTED_FORMATS

    missing = baseline_formats - current_formats
    assert not missing, (
        f"Formats removed since baseline: {missing}. "
        f"Baseline had {sorted(baseline_formats)}, now {sorted(current_formats)}"
    )


# ---------------------------------------------------------------------------
# Regression: multi-format parsing output must be stable
# ---------------------------------------------------------------------------

def test_multiformat_parsing_regression(tmp_path):
    """Title detection, TOC counts, and table extraction must match baseline."""
    baseline = _load_baseline()
    b = baseline.get("multiformat_parsing", {})
    if not b:
        return

    from docx import Document as DocxDocument

    # Recreate the exact same sample files used by _generate_baseline.py
    sample_md = tmp_path / "sample.md"
    sample_md.write_text(
        "# Machine Learning Primer\n\n"
        "## Supervised Learning\n\n"
        "Supervised learning trains models on labeled data.\n\n"
        "## Unsupervised Learning\n\n"
        "Unsupervised learning finds patterns without labels.\n\n"
        "| Method | Type |\n| --- | --- |\n| K-means | Clustering |\n| PCA | Reduction |\n"
    )
    sample_txt = tmp_path / "sample.txt"
    sample_txt.write_text(
        "Introduction to Neural Networks\n\n"
        "Neural networks are computing systems inspired by biological neural networks.\n"
        "They consist of layers of interconnected nodes called neurons.\n\n"
        "Deep learning uses multiple layers to progressively extract features.\n"
    )
    sample_html = tmp_path / "sample.html"
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
    sample_docx = tmp_path / "sample.docx"
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

    files = {"md": sample_md, "txt": sample_txt, "html": sample_html, "docx": sample_docx}

    print(f"\n--- Multi-Format Parsing Regression ---")
    for ext, path in files.items():
        expected = b["results"].get(ext)
        if not expected:
            continue

        parsed = parse_document(path)

        print(f"  {ext}: title={parsed.title!r}, toc={len(parsed.toc)}, format={parsed.source_format}")

        assert parsed.title == expected["title_detected"], (
            f"{ext}: title changed: {parsed.title!r} vs baseline {expected['title_detected']!r}"
        )
        assert parsed.source_format == expected["source_format"], (
            f"{ext}: source_format changed: {parsed.source_format!r} vs baseline {expected['source_format']!r}"
        )
        assert len(parsed.toc) == expected["toc_entries"], (
            f"{ext}: TOC entries changed: {len(parsed.toc)} vs baseline {expected['toc_entries']}"
        )
        has_table = "|" in parsed.full_markdown
        assert has_table == expected["has_table"], (
            f"{ext}: table detection changed: {has_table} vs baseline {expected['has_table']}"
        )
        content_tokens = count_tokens(parsed.full_markdown) if parsed.full_markdown else 0
        assert content_tokens == expected["content_tokens"], (
            f"{ext}: token count changed: {content_tokens} vs baseline {expected['content_tokens']}"
        )


# ---------------------------------------------------------------------------
# Regression: semantic chunking output must be stable
# ---------------------------------------------------------------------------

def test_semantic_chunking_regression(tmp_path):
    """Semantic chunking chunk count and token stats must match baseline."""
    from unittest.mock import MagicMock
    import numpy as np

    baseline = _load_baseline()
    b = baseline.get("semantic_chunking", {})
    if not b:
        return

    # Reproduce the exact same multi-topic document from _generate_baseline.py
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
    content = (
        " ".join(topic_a_sents) + "\n\n"
        + " ".join(topic_b_sents) + "\n\n"
        + " ".join(topic_c_sents)
    )

    sec = StructureNode(id="sec-topics", title="Mixed Topics", level=2, content=content)
    ch = StructureNode(id="ch1", title="Chapter 1", level=1, page_start=1, page_end=3, children=[sec])
    root = StructureNode(id="root", title="Multi-Topic Doc", level=0, page_end=3, children=[ch])
    structure = DocumentStructure(doc_id="semantic-baseline", title="Multi-Topic Doc", root=root)

    # Reproduce the exact same deterministic embedder
    rng = np.random.RandomState(42)
    dim = 64
    center_a = rng.randn(dim); center_a /= np.linalg.norm(center_a)
    center_b = rng.randn(dim); center_b /= np.linalg.norm(center_b)
    center_c = rng.randn(dim); center_c /= np.linalg.norm(center_c)

    def mock_embed(texts):
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
            v = base + rng.randn(dim) * 0.05
            v /= np.linalg.norm(v)
            vectors.append(v.tolist())
        return vectors

    embedder = MagicMock()
    embedder.embed_passages.side_effect = mock_embed

    settings = Settings(
        data_dir=tmp_path, chunking_strategy="semantic",
        max_chunk_tokens=120, min_chunk_tokens=30, semantic_threshold_percentile=25,
    )

    chunks = chunk_document(structure, settings, embedder=embedder)
    sem = b["semantic"]

    sizes = sorted(count_tokens(c.content) for c in chunks.l3_chunks)

    print(f"\n--- Semantic Chunking Regression ---")
    print(f"  L3 passages: {len(chunks.l3_chunks)} (baseline {sem['l3_passages']})")
    print(f"  Total tokens: {sum(sizes)} (baseline {sem['total_tokens']})")
    print(f"  Token range: [{sizes[0]}-{sizes[-1]}] (baseline [{sem['token_min']}-{sem['token_max']}])")

    assert len(chunks.l3_chunks) == sem["l3_passages"], (
        f"Semantic L3 count changed: {len(chunks.l3_chunks)} vs baseline {sem['l3_passages']}"
    )
    assert sum(sizes) == sem["total_tokens"], (
        f"Semantic total tokens changed: {sum(sizes)} vs baseline {sem['total_tokens']}"
    )
    assert sizes[0] == sem["token_min"], (
        f"Semantic token min changed: {sizes[0]} vs baseline {sem['token_min']}"
    )
    assert sizes[-1] == sem["token_max"], (
        f"Semantic token max changed: {sizes[-1]} vs baseline {sem['token_max']}"
    )
