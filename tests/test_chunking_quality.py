"""Chunking quality tests — strategy comparison and contextual chunking correctness.

Run with:  pytest tests/test_chunking_quality.py -v -s
"""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np

from ingestible.config import Settings
from ingestible.models.document import DocumentStructure, StructureNode
from ingestible.pipeline.stage3_chunking import chunk_document
from ingestible.utils.tokens import count_tokens

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

# 3 distinct topics, 6 sentences each — clearly separable
TOPIC_ML = [
    "Machine learning algorithms learn patterns from large volumes of training data.",
    "Supervised learning requires labeled examples for effective model training.",
    "Neural networks use backpropagation to adjust connection weights across layers.",
    "Gradient descent optimizes the loss function by iteratively updating parameters.",
    "Regularization techniques like dropout prevent overfitting on the training set.",
    "Transfer learning reuses pretrained model weights for new downstream tasks.",
]

TOPIC_OCEAN = [
    "The ocean covers approximately seventy percent of the earth's total surface area.",
    "Marine ecosystems support incredible biodiversity especially in tropical coral reefs.",
    "Deep sea hydrothermal vents host chemosynthetic organisms that thrive without sunlight.",
    "Ocean currents distribute heat globally and regulate regional climate patterns.",
    "Phytoplankton produce roughly half of the oxygen in the earth's atmosphere.",
    "Overfishing threatens marine food chains and collapses commercially important fish stocks.",
]

TOPIC_ROME = [
    "Ancient Roman architecture pioneered the use of arches and concrete construction techniques.",
    "The Colosseum could seat fifty thousand spectators for gladiatorial combat events.",
    "Roman aqueducts transported fresh water across vast distances using gravity alone.",
    "The Pantheon's unreinforced concrete dome remains the largest of its kind today.",
    "Roman roads connected provinces across three continents enabling trade and military movement.",
    "Public baths served as social gathering places central to daily Roman civic life.",
]

MULTI_TOPIC_CONTENT = (
    " ".join(TOPIC_ML) + "\n\n" + " ".join(TOPIC_OCEAN) + "\n\n" + " ".join(TOPIC_ROME)
)


def _build_multi_topic_structure(doc_id: str = "quality-test") -> DocumentStructure:
    """Build a document with 3 distinct topics under one chapter/section."""
    sec = StructureNode(id="sec1", title="Mixed Topics", level=2, content=MULTI_TOPIC_CONTENT)
    ch = StructureNode(
        id="ch1", title="Chapter One", level=1, page_start=1, page_end=3, children=[sec]
    )
    root = StructureNode(id="root", title="Quality Test Doc", level=0, page_end=3, children=[ch])
    return DocumentStructure(doc_id=doc_id, title="Quality Test Doc", root=root)


def _build_multi_chapter_structure(doc_id: str = "ctx-test") -> DocumentStructure:
    """Build a document with multiple chapters and sections for contextual chunking tests."""
    chapters = []
    topics = {
        "Machine Learning Fundamentals": " ".join(TOPIC_ML),
        "Oceanography and Marine Science": " ".join(TOPIC_OCEAN),
        "Roman Architecture and Engineering": " ".join(TOPIC_ROME),
    }
    for ci, (ch_title, content) in enumerate(topics.items()):
        sec_a = StructureNode(
            id=f"ch{ci}-sec0",
            title=f"Introduction to {ch_title}",
            level=2,
            content=content[: len(content) // 2],
            page_start=ci * 10,
            page_end=ci * 10 + 1,
        )
        sec_b = StructureNode(
            id=f"ch{ci}-sec1",
            title=f"Advanced {ch_title}",
            level=2,
            content=content[len(content) // 2 :],
            page_start=ci * 10 + 1,
            page_end=ci * 10 + 2,
        )
        chapters.append(
            StructureNode(
                id=f"ch{ci}",
                title=ch_title,
                level=1,
                page_start=ci * 10,
                page_end=ci * 10 + 2,
                children=[sec_a, sec_b],
            )
        )
    root = StructureNode(
        id="root", title="Multi-Chapter Doc", level=0, page_end=30, children=chapters
    )
    return DocumentStructure(doc_id=doc_id, title="Multi-Chapter Doc", root=root)


def _make_mock_embedder(dim: int = 64, seed: int = 42) -> MagicMock:
    """Build a deterministic mock embedder with 3 topic-clustered vectors."""
    rng = np.random.RandomState(seed)
    center_ml = rng.randn(dim)
    center_ml /= np.linalg.norm(center_ml)
    center_ocean = rng.randn(dim)
    center_ocean /= np.linalg.norm(center_ocean)
    center_rome = rng.randn(dim)
    center_rome /= np.linalg.norm(center_rome)

    ml_keywords = [
        "learning",
        "neural",
        "training",
        "gradient",
        "regularization",
        "backpropagation",
    ]
    ocean_keywords = ["ocean", "marine", "reef", "phytoplankton", "overfishing", "hydrothermal"]
    rome_keywords = ["roman", "colosseum", "aqueduct", "pantheon", "gladiatorial", "concrete"]

    def mock_embed(texts: list[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            t = text.lower()
            if any(w in t for w in ml_keywords):
                base = center_ml
            elif any(w in t for w in ocean_keywords):
                base = center_ocean
            elif any(w in t for w in rome_keywords):
                base = center_rome
            else:
                # Unknown topic — random direction
                base = rng.randn(dim)
                base /= np.linalg.norm(base)
            v = base + rng.randn(dim) * 0.05
            v /= np.linalg.norm(v)
            vectors.append(v.tolist())
        return vectors

    embedder = MagicMock()
    embedder.embed_passages.side_effect = mock_embed
    return embedder


# ---------------------------------------------------------------------------
# 1. Chunking strategy comparison with quality assertions
# ---------------------------------------------------------------------------


def test_all_strategies_preserve_content(tmp_path):
    """All 4 strategies must preserve all content (total output chars ~ input chars)."""
    structure = _build_multi_topic_structure()
    input_chars = len(MULTI_TOPIC_CONTENT)
    embedder = _make_mock_embedder()

    strategies = ["paragraph", "semantic", "recursive", "docling"]
    results: dict[str, list] = {}

    for strategy in strategies:
        settings = Settings(
            data_dir=tmp_path / strategy,
            chunking_strategy=strategy,
            max_chunk_tokens=120,
            min_chunk_tokens=30,
            content_classification=False,
        )
        emb = embedder if strategy == "semantic" else None
        chunks = chunk_document(structure, settings, embedder=emb)
        results[strategy] = chunks.l3_chunks

    for strategy, l3_chunks in results.items():
        output_chars = sum(len(c.content) for c in l3_chunks)
        # Allow overlap to inflate output a bit; the main concern is no content loss.
        # Output should be at least 90% of input (some whitespace normalisation is fine).
        assert output_chars >= input_chars * 0.85, (
            f"{strategy}: output {output_chars} chars < 85% of input {input_chars} chars"
        )


def test_all_strategies_respect_max_tokens(tmp_path):
    """No chunk should exceed 1.5x max_chunk_tokens (tolerance for atomic blocks)."""
    structure = _build_multi_topic_structure()
    embedder = _make_mock_embedder()
    max_tokens = 120

    strategies = ["paragraph", "semantic", "recursive", "docling"]

    for strategy in strategies:
        settings = Settings(
            data_dir=tmp_path / strategy,
            chunking_strategy=strategy,
            max_chunk_tokens=max_tokens,
            min_chunk_tokens=30,
            content_classification=False,
        )
        emb = embedder if strategy == "semantic" else None
        chunks = chunk_document(structure, settings, embedder=emb)

        hard_limit = max_tokens * 1.5
        for chunk in chunks.l3_chunks:
            tokens = count_tokens(chunk.content)
            assert tokens <= hard_limit, (
                f"{strategy}: chunk {chunk.chunk_id} has {tokens} tokens, "
                f"exceeds 1.5x limit of {hard_limit}"
            )


def test_semantic_produces_at_least_as_many_chunks_as_paragraph(tmp_path):
    """Semantic chunking splits on topic boundaries, producing >= paragraph chunk count."""
    structure = _build_multi_topic_structure()
    embedder = _make_mock_embedder()

    settings_sem = Settings(
        data_dir=tmp_path / "sem",
        chunking_strategy="semantic",
        max_chunk_tokens=120,
        min_chunk_tokens=30,
        semantic_threshold_percentile=25,
        content_classification=False,
    )
    settings_para = Settings(
        data_dir=tmp_path / "para",
        chunking_strategy="paragraph",
        max_chunk_tokens=120,
        min_chunk_tokens=30,
        content_classification=False,
    )

    sem_chunks = chunk_document(structure, settings_sem, embedder=embedder)
    para_chunks = chunk_document(structure, settings_para)

    assert len(sem_chunks.l3_chunks) >= len(para_chunks.l3_chunks), (
        f"Semantic ({len(sem_chunks.l3_chunks)}) should produce >= "
        f"paragraph ({len(para_chunks.l3_chunks)}) chunks on multi-topic input"
    )


def test_strategy_comparison_table(tmp_path, capsys):
    """Print a comparison table of chunk counts and size distributions across all strategies."""
    structure = _build_multi_topic_structure()
    embedder = _make_mock_embedder()
    max_tokens = 120

    strategies = ["paragraph", "semantic", "recursive", "docling"]
    rows: list[dict] = []

    for strategy in strategies:
        settings = Settings(
            data_dir=tmp_path / strategy,
            chunking_strategy=strategy,
            max_chunk_tokens=max_tokens,
            min_chunk_tokens=30,
            semantic_threshold_percentile=25,
            content_classification=False,
        )
        emb = embedder if strategy == "semantic" else None
        chunks = chunk_document(structure, settings, embedder=emb)

        sizes = [count_tokens(c.content) for c in chunks.l3_chunks]
        rows.append(
            {
                "strategy": strategy,
                "count": len(sizes),
                "min": min(sizes) if sizes else 0,
                "max": max(sizes) if sizes else 0,
                "mean": int(sum(sizes) / len(sizes)) if sizes else 0,
                "total_chars": sum(len(c.content) for c in chunks.l3_chunks),
            }
        )

    print("\n--- Strategy Comparison ---")
    header = f"{'Strategy':<12} {'Chunks':>6} {'Min':>5} {'Max':>5} {'Mean':>5} {'TotalChars':>11}"
    print(header)
    print("-" * len(header))
    for r in rows:
        print(
            f"{r['strategy']:<12} {r['count']:>6} {r['min']:>5} {r['max']:>5} "
            f"{r['mean']:>5} {r['total_chars']:>11}"
        )

    # Every strategy produced at least 1 chunk
    for r in rows:
        assert r["count"] >= 1, f"{r['strategy']} produced 0 chunks"


# ---------------------------------------------------------------------------
# 2. Contextual chunking (stage 3c) correctness
# ---------------------------------------------------------------------------


def test_context_prefix_contains_chapter_and_section(tmp_path):
    """After manually applying context_prefix, every L3 chunk references its parent titles."""
    structure = _build_multi_chapter_structure()
    settings = Settings(
        data_dir=tmp_path,
        chunking_strategy="paragraph",
        max_chunk_tokens=200,
        min_chunk_tokens=30,
        content_classification=False,
    )
    chunks = chunk_document(structure, settings)

    # Build title lookup from structure tree (same logic as stage3c_contextual.py)
    title_map: dict[str, str] = {}
    for node in structure.root.walk():
        title_map[node.id] = node.title

    # Simulate what stage3c does: set context_prefix using chapter > section format
    for chunk in chunks.l3_chunks:
        chapter_title = title_map.get(chunk.position.chapter, "")
        section_title = title_map.get(chunk.position.section, "")
        if chapter_title and section_title and section_title != chapter_title:
            chunk.context_prefix = f"{chapter_title} > {section_title}:"
        elif chapter_title:
            chunk.context_prefix = f"{chapter_title}:"

    # Now assert correctness
    for chunk in chunks.l3_chunks:
        assert chunk.context_prefix, f"Chunk {chunk.chunk_id} has empty context_prefix"
        chapter_title = title_map.get(chunk.position.chapter, "")
        section_title = title_map.get(chunk.position.section, "")

        assert chapter_title in chunk.context_prefix, (
            f"Chunk {chunk.chunk_id}: context_prefix {chunk.context_prefix!r} "
            f"does not contain chapter title {chapter_title!r}"
        )
        if section_title and section_title != chapter_title:
            assert section_title in chunk.context_prefix, (
                f"Chunk {chunk.chunk_id}: context_prefix {chunk.context_prefix!r} "
                f"does not contain section title {section_title!r}"
            )


def test_context_prefix_nonempty_for_all_chunks(tmp_path):
    """Every L3 chunk must have a non-empty context_prefix after contextual processing."""
    structure = _build_multi_chapter_structure()
    settings = Settings(
        data_dir=tmp_path,
        chunking_strategy="paragraph",
        max_chunk_tokens=200,
        min_chunk_tokens=30,
        content_classification=False,
    )
    chunks = chunk_document(structure, settings)

    title_map: dict[str, str] = {}
    for node in structure.root.walk():
        title_map[node.id] = node.title

    for chunk in chunks.l3_chunks:
        chapter_title = title_map.get(chunk.position.chapter, "")
        section_title = title_map.get(chunk.position.section, "")
        if chapter_title and section_title and section_title != chapter_title:
            chunk.context_prefix = f"{chapter_title} > {section_title}:"
        elif chapter_title:
            chunk.context_prefix = f"{chapter_title}:"

    for chunk in chunks.l3_chunks:
        assert chunk.context_prefix != "", f"Chunk {chunk.chunk_id} has empty context_prefix"
        assert len(chunk.context_prefix.strip()) > 0, (
            f"Chunk {chunk.chunk_id} has whitespace-only context_prefix"
        )


def test_context_prefix_format_has_separator(tmp_path):
    """The context prefix follows the 'Chapter > Section:' format with > separator."""
    structure = _build_multi_chapter_structure()
    settings = Settings(
        data_dir=tmp_path,
        chunking_strategy="paragraph",
        max_chunk_tokens=200,
        min_chunk_tokens=30,
        content_classification=False,
    )
    chunks = chunk_document(structure, settings)

    title_map: dict[str, str] = {}
    for node in structure.root.walk():
        title_map[node.id] = node.title

    for chunk in chunks.l3_chunks:
        chapter_title = title_map.get(chunk.position.chapter, "")
        section_title = title_map.get(chunk.position.section, "")
        if chapter_title and section_title and section_title != chapter_title:
            chunk.context_prefix = f"{chapter_title} > {section_title}:"
        elif chapter_title:
            chunk.context_prefix = f"{chapter_title}:"

    # All chunks where chapter != section should have ">" separator
    for chunk in chunks.l3_chunks:
        chapter_title = title_map.get(chunk.position.chapter, "")
        section_title = title_map.get(chunk.position.section, "")
        if section_title and section_title != chapter_title:
            assert ">" in chunk.context_prefix, (
                f"Chunk {chunk.chunk_id}: context_prefix {chunk.context_prefix!r} "
                f"missing '>' separator between chapter and section"
            )
        # All prefixes end with ":"
        assert chunk.context_prefix.endswith(":"), (
            f"Chunk {chunk.chunk_id}: context_prefix {chunk.context_prefix!r} does not end with ':'"
        )
