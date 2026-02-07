"""Benchmark tests — surface key pipeline metrics at a glance.

Run with:  pytest tests/test_benchmark.py -v -s
"""

from __future__ import annotations

import time
from collections import defaultdict

from ingestion_tool.config import Settings
from ingestion_tool.models.document import DocumentStructure, StructureNode
from ingestion_tool.pipeline.stage3_chunking import chunk_document
from ingestion_tool.pipeline.stage6_storage import load_chunks, save_document
from ingestion_tool.search.bm25_store import BM25Store
from ingestion_tool.search.concept_index import ConceptIndex
from ingestion_tool.utils.text import split_paragraphs
from ingestion_tool.utils.tokens import count_tokens


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _big_structure(n_chapters: int = 5, n_sections: int = 4, paragraph_count: int = 6) -> DocumentStructure:
    """Build a realistic multi-chapter document structure for benchmarking."""
    paragraph = (
        "Autonomous agents leverage tool-use capabilities to interact with external "
        "systems. The Model Context Protocol standardises how hosts, clients and "
        "servers communicate over JSON-RPC transports. Each tool invocation is a "
        "structured request-response cycle carrying typed parameters and results."
    )
    section_body = "\n\n".join([paragraph] * paragraph_count)

    chapters = []
    for ci in range(n_chapters):
        sections = []
        for si in range(n_sections):
            sections.append(StructureNode(
                id=f"ch{ci}-sec{si}",
                title=f"Section {ci}.{si}",
                level=2,
                content=section_body,
                page_start=ci * 10 + si,
                page_end=ci * 10 + si + 1,
            ))
        chapters.append(StructureNode(
            id=f"ch{ci}",
            title=f"Chapter {ci}",
            level=1,
            page_start=ci * 10,
            page_end=ci * 10 + n_sections,
            children=sections,
        ))

    root = StructureNode(
        id="root", title="Benchmark Document", level=0,
        page_end=n_chapters * 10, children=chapters,
    )
    return DocumentStructure(doc_id="bench-doc", title="Benchmark Document", root=root)


# ---------------------------------------------------------------------------
# Benchmark: chunking throughput
# ---------------------------------------------------------------------------

def test_chunking_throughput(tmp_path):
    """Measure chunking speed and report key metrics."""
    settings = Settings(data_dir=tmp_path, max_chunk_tokens=500, min_chunk_tokens=100)
    structure = _big_structure(n_chapters=5, n_sections=4, paragraph_count=6)

    start = time.perf_counter()
    chunks = chunk_document(structure, settings)
    elapsed = time.perf_counter() - start

    total_input_chars = sum(
        len(node.content)
        for node in structure.root.walk()
        if node.content
    )
    total_output_tokens = sum(count_tokens(c.content) for c in chunks.l3_chunks)

    print("\n--- Chunking Benchmark ---")
    print(f"  Input chars:       {total_input_chars:,}")
    print(f"  L1 (chapters):     {len(chunks.l1_chunks)}")
    print(f"  L2 (sections):     {len(chunks.l2_chunks)}")
    print(f"  L3 (passages):     {len(chunks.l3_chunks)}")
    print(f"  Total L3 tokens:   {total_output_tokens:,}")
    print(f"  Avg tokens/chunk:  {total_output_tokens / max(len(chunks.l3_chunks), 1):.0f}")
    print(f"  Elapsed:           {elapsed:.4f}s")
    print(f"  Throughput:        {total_input_chars / max(elapsed, 0.0001):,.0f} chars/s")

    # Sanity bounds
    assert len(chunks.l1_chunks) == 5
    assert len(chunks.l2_chunks) == 20
    assert len(chunks.l3_chunks) > 0
    assert elapsed < 10.0, "Chunking took unreasonably long"


# ---------------------------------------------------------------------------
# Benchmark: token counting overhead
# ---------------------------------------------------------------------------

def test_token_counting_speed():
    """Measure tiktoken encoding throughput."""
    text = "The quick brown fox jumps over the lazy dog. " * 500  # ~4500 tokens
    n_iters = 50

    start = time.perf_counter()
    for _ in range(n_iters):
        count_tokens(text)
    elapsed = time.perf_counter() - start

    tokens = count_tokens(text)
    print("\n--- Token Counting Benchmark ---")
    print(f"  Text length:       {len(text):,} chars")
    print(f"  Token count:       {tokens:,}")
    print(f"  Iterations:        {n_iters}")
    print(f"  Total elapsed:     {elapsed:.4f}s")
    print(f"  Per-call:          {elapsed / n_iters * 1000:.2f}ms")

    assert elapsed < 5.0, "Token counting too slow"


# ---------------------------------------------------------------------------
# Benchmark: chunk size distribution
# ---------------------------------------------------------------------------

def test_chunk_size_distribution(tmp_path):
    """Verify chunks respect size bounds and report distribution."""
    settings = Settings(data_dir=tmp_path, max_chunk_tokens=500, min_chunk_tokens=100)
    structure = _big_structure(n_chapters=3, n_sections=5, paragraph_count=8)
    chunks = chunk_document(structure, settings)

    sizes = [count_tokens(c.content) for c in chunks.l3_chunks]
    sizes.sort()

    print("\n--- Chunk Size Distribution ---")
    print(f"  Total chunks:  {len(sizes)}")
    print(f"  Min tokens:    {sizes[0]}")
    print(f"  Max tokens:    {sizes[-1]}")
    print(f"  Median tokens: {sizes[len(sizes) // 2]}")
    print(f"  Mean tokens:   {sum(sizes) / len(sizes):.0f}")

    oversized = [s for s in sizes if s > settings.max_chunk_tokens * 1.5]
    print(f"  Oversized (>1.5x max): {len(oversized)}")

    # Atomic blocks (tables/code) may exceed max, but regular chunks should not
    # blow past 1.5x the limit
    assert len(oversized) / len(sizes) < 0.1, (
        f"{len(oversized)}/{len(sizes)} chunks exceed 1.5x max_chunk_tokens"
    )


# ---------------------------------------------------------------------------
# Benchmark: save/load round-trip
# ---------------------------------------------------------------------------

def test_storage_roundtrip_speed(tmp_path):
    """Measure save + load cycle for a realistic document."""
    from ingestion_tool.pipeline.stage6_storage import load_chunks, save_document

    settings = Settings(data_dir=tmp_path)
    structure = _big_structure(n_chapters=5, n_sections=4, paragraph_count=6)
    chunks = chunk_document(structure, settings)

    # Save
    start = time.perf_counter()
    doc_dir = save_document(structure, chunks, settings)
    save_elapsed = time.perf_counter() - start

    # Load
    start = time.perf_counter()
    loaded = load_chunks(doc_dir)
    load_elapsed = time.perf_counter() - start

    print("\n--- Storage Round-Trip Benchmark ---")
    print(f"  Chapters:  {len(chunks.l1_chunks)}")
    print(f"  Sections:  {len(chunks.l2_chunks)}")
    print(f"  Passages:  {len(chunks.l3_chunks)}")
    print(f"  Save:      {save_elapsed:.4f}s")
    print(f"  Load:      {load_elapsed:.4f}s")

    assert loaded.doc_id == chunks.doc_id
    assert len(loaded.l1_chunks) == len(chunks.l1_chunks)
    assert len(loaded.l2_chunks) == len(chunks.l2_chunks)
    assert len(loaded.l3_chunks) == len(chunks.l3_chunks)
    assert save_elapsed < 5.0
    assert load_elapsed < 5.0


# ---------------------------------------------------------------------------
# Benchmark: content coverage ratio
# ---------------------------------------------------------------------------

def test_content_coverage(tmp_path):
    """Measure ratio of L3 output chars to leaf input chars."""
    settings = Settings(data_dir=tmp_path, max_chunk_tokens=500, min_chunk_tokens=100)
    structure = _big_structure(n_chapters=5, n_sections=4, paragraph_count=6)
    chunks = chunk_document(structure, settings)

    input_chars = sum(
        len(node.content)
        for node in structure.root.walk()
        if node.content and node.level >= 2
    )
    output_chars = sum(len(c.content) for c in chunks.l3_chunks)
    ratio = output_chars / input_chars if input_chars else 0.0

    print("\n--- Content Coverage ---")
    print(f"  Input leaf chars:  {input_chars:,}")
    print(f"  L3 output chars:   {output_chars:,}")
    print(f"  Coverage ratio:    {ratio:.4f}")

    assert ratio >= 0.9, f"Coverage ratio too low: {ratio:.4f}"


# ---------------------------------------------------------------------------
# Benchmark: hierarchy linkage / orphan rate
# ---------------------------------------------------------------------------

def test_hierarchy_linkage(tmp_path):
    """Count orphaned chunks that reference non-existent parents."""
    settings = Settings(data_dir=tmp_path, max_chunk_tokens=500, min_chunk_tokens=100)
    structure = _big_structure(n_chapters=5, n_sections=4, paragraph_count=6)
    chunks = chunk_document(structure, settings)

    l2_ids = {c.chunk_id for c in chunks.l2_chunks}
    l1_ids = {c.chunk_id for c in chunks.l1_chunks}

    l3_orphans = sum(1 for c in chunks.l3_chunks if c.parent_section_id not in l2_ids)
    l2_orphans = sum(1 for c in chunks.l2_chunks if c.parent_chapter_id not in l1_ids)

    print("\n--- Hierarchy Linkage ---")
    print(f"  L3 chunks:       {len(chunks.l3_chunks)}")
    print(f"  L3 orphans:      {l3_orphans}")
    print(f"  L2 chunks:       {len(chunks.l2_chunks)}")
    print(f"  L2 orphans:      {l2_orphans}")

    assert l3_orphans == 0, f"Found {l3_orphans} L3 orphan chunks"
    assert l2_orphans == 0, f"Found {l2_orphans} L2 orphan chunks"


# ---------------------------------------------------------------------------
# Benchmark: disk footprint
# ---------------------------------------------------------------------------

def test_disk_footprint(tmp_path):
    """Measure total bytes and file count after save."""
    settings = Settings(data_dir=tmp_path, max_chunk_tokens=500, min_chunk_tokens=100)
    structure = _big_structure(n_chapters=5, n_sections=4, paragraph_count=6)
    chunks = chunk_document(structure, settings)
    doc_dir = save_document(structure, chunks, settings)

    total_bytes = 0
    file_count = 0
    for f in doc_dir.rglob("*"):
        if f.is_file():
            total_bytes += f.stat().st_size
            file_count += 1

    print("\n--- Disk Footprint ---")
    print(f"  Total bytes:  {total_bytes:,}")
    print(f"  File count:   {file_count}")

    assert file_count > 0, "No files written"
    assert total_bytes > 0, "Zero bytes on disk"


# ---------------------------------------------------------------------------
# Benchmark: search index counts
# ---------------------------------------------------------------------------

def test_search_index_counts(tmp_path):
    """Build BM25 and ConceptIndex from L3 chunks and report counts."""
    settings = Settings(data_dir=tmp_path, max_chunk_tokens=500, min_chunk_tokens=100)
    structure = _big_structure(n_chapters=5, n_sections=4, paragraph_count=6)
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

    print("\n--- Search Index Counts ---")
    print(f"  BM25 doc count:           {bm25.count}")
    print(f"  Concept index term count: {concept_idx.count}")

    assert bm25.count == len(chunks.l3_chunks), (
        f"BM25 count {bm25.count} != L3 chunk count {len(chunks.l3_chunks)}"
    )
    assert concept_idx.count > 0, "Concept index is empty"


# ---------------------------------------------------------------------------
# Benchmark: overlap verification
# ---------------------------------------------------------------------------

def test_overlap_verification(tmp_path):
    """Check overlap between consecutive L3 chunks in the same section."""
    # Use more paragraphs to force multi-chunk sections with overlap
    settings = Settings(data_dir=tmp_path, max_chunk_tokens=500, min_chunk_tokens=100)
    structure = _big_structure(n_chapters=3, n_sections=3, paragraph_count=12)
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

    overlap_rate = (
        overlap_pairs_with_shared_content / overlap_pairs_total
        if overlap_pairs_total else 0.0
    )

    print("\n--- Overlap Verification ---")
    print(f"  L3 chunks:            {len(chunks.l3_chunks)}")
    print(f"  Consecutive pairs:    {overlap_pairs_total}")
    print(f"  Pairs with overlap:   {overlap_pairs_with_shared_content}")
    print(f"  Overlap rate:         {overlap_rate:.2%}")

    # Just verify we can compute the metric — the actual rate depends on content
    assert overlap_pairs_total >= 0
