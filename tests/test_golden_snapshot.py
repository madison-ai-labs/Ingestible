"""Golden-file snapshot tests — verify exact chunking output for known inputs.

For a deterministic input document, assert the exact set of chunks produced
(count, IDs, content, hierarchy). This catches any drift in the chunking
algorithm that might slip past threshold-based tests.

Run with:  pytest tests/test_golden_snapshot.py -v
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ingestible.config import Settings
from ingestible.models.document import DocumentStructure, StructureNode
from ingestible.pipeline.stage3_chunking import chunk_document
from ingestible.utils.tokens import count_tokens

GOLDEN_PATH = Path(__file__).parent / "golden_chunks_v1.json"


def _build_golden_document() -> DocumentStructure:
    """Build a deterministic document with varied structure for snapshot testing.

    Three chapters with different content shapes:
    - Chapter 1: two sections, short paragraphs (below chunk limit)
    - Chapter 2: one section, long content (forces splitting)
    - Chapter 3: one section with a markdown table (atomic block)
    """
    ch1_sec1_content = (
        "Machine learning is a subset of artificial intelligence. "
        "It enables systems to learn and improve from experience without being explicitly programmed. "
        "The field has grown rapidly since the advent of deep learning in 2012."
    )
    ch1_sec2_content = (
        "Supervised learning uses labeled training data. "
        "Common algorithms include logistic regression, random forests, and neural networks. "
        "The goal is to learn a mapping from inputs to outputs."
    )

    # Long content that must be split into multiple chunks
    ch2_sentences = [
        "Natural language processing deals with the interaction between computers and human language.",
        "Tokenization splits text into individual words or subword units for processing.",
        "Word embeddings represent words as dense vectors in a continuous vector space.",
        "Attention mechanisms allow models to focus on relevant parts of the input sequence.",
        "Transformer architectures replaced recurrent networks as the dominant paradigm.",
        "Pre-training on large corpora followed by fine-tuning has become the standard approach.",
        "Language models predict the probability of the next token given previous context.",
        "Encoder-decoder architectures are used for sequence-to-sequence tasks like translation.",
        "Self-attention computes relationships between all positions in a sequence simultaneously.",
        "Positional encodings inject information about token order into the model.",
        "Multi-head attention runs several attention functions in parallel for richer representations.",
        "Layer normalization and residual connections stabilize training of deep transformer networks.",
    ]
    ch2_content = " ".join(ch2_sentences)

    # Table content — should be kept atomic
    ch3_content = (
        "The following table compares model architectures:\n\n"
        "| Model | Parameters | Training Data | Year |\n"
        "| --- | --- | --- | --- |\n"
        "| BERT | 340M | BooksCorpus + Wikipedia | 2018 |\n"
        "| GPT-2 | 1.5B | WebText | 2019 |\n"
        "| T5 | 11B | C4 | 2020 |\n"
        "| GPT-3 | 175B | Common Crawl + Books | 2020 |\n\n"
        "Each model introduced architectural innovations that advanced the field."
    )

    structure = DocumentStructure(
        doc_id="golden-doc",
        title="ML Survey",
        root=StructureNode(
            id="root",
            title="ML Survey",
            level=0,
            page_end=30,
            children=[
                StructureNode(
                    id="ch1",
                    title="Foundations",
                    level=1,
                    page_start=1,
                    page_end=10,
                    children=[
                        StructureNode(
                            id="ch1-sec1",
                            title="Overview",
                            level=2,
                            content=ch1_sec1_content,
                            page_start=1,
                            page_end=5,
                        ),
                        StructureNode(
                            id="ch1-sec2",
                            title="Supervised Learning",
                            level=2,
                            content=ch1_sec2_content,
                            page_start=6,
                            page_end=10,
                        ),
                    ],
                ),
                StructureNode(
                    id="ch2",
                    title="NLP",
                    level=1,
                    page_start=11,
                    page_end=20,
                    children=[
                        StructureNode(
                            id="ch2-sec1",
                            title="Transformers",
                            level=2,
                            content=ch2_content,
                            page_start=11,
                            page_end=20,
                        ),
                    ],
                ),
                StructureNode(
                    id="ch3",
                    title="Models",
                    level=1,
                    page_start=21,
                    page_end=30,
                    children=[
                        StructureNode(
                            id="ch3-sec1",
                            title="Comparison",
                            level=2,
                            content=ch3_content,
                            page_start=21,
                            page_end=30,
                        ),
                    ],
                ),
            ],
        ),
    )
    return structure


def _generate_golden(settings: Settings) -> dict:
    """Generate the golden snapshot from a fresh run."""
    structure = _build_golden_document()
    chunks = chunk_document(structure, settings)

    snapshot = {
        "settings": {
            "max_chunk_tokens": settings.max_chunk_tokens,
            "min_chunk_tokens": settings.min_chunk_tokens,
            "chunking_strategy": settings.chunking_strategy,
        },
        "counts": {
            "l1": len(chunks.l1_chunks),
            "l2": len(chunks.l2_chunks),
            "l3": len(chunks.l3_chunks),
        },
        "l3_chunks": [],
    }

    for c in sorted(chunks.l3_chunks, key=lambda x: x.chunk_id):
        snapshot["l3_chunks"].append(
            {
                "chunk_id": c.chunk_id,
                "parent_section_id": c.parent_section_id,
                "content_length": len(c.content),
                "token_count": count_tokens(c.content),
                "content_hash": hash(c.content) & 0xFFFFFFFF,  # 32-bit for portability
                "first_50_chars": c.content[:50],
                "position": {
                    "chapter": c.position.chapter,
                    "section": c.position.section,
                    "index": c.position.index,
                },
            }
        )

    return snapshot


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path,
        max_chunk_tokens=200,
        min_chunk_tokens=30,
        chunking_strategy="paragraph",
    )


class TestGoldenSnapshot:
    def test_generate_or_verify_snapshot(self, tmp_path):
        """If golden file exists, verify against it. Otherwise, generate it.

        To regenerate: delete tests/golden_chunks_v1.json and re-run.
        """
        settings = _settings(tmp_path)

        if not GOLDEN_PATH.exists():
            snapshot = _generate_golden(settings)
            GOLDEN_PATH.write_text(json.dumps(snapshot, indent=2) + "\n")
            pytest.skip("Generated golden snapshot — re-run to verify")

        golden = json.loads(GOLDEN_PATH.read_text())
        structure = _build_golden_document()
        chunks = chunk_document(structure, settings)

        # Verify counts
        assert len(chunks.l1_chunks) == golden["counts"]["l1"], (
            f"L1 count: {len(chunks.l1_chunks)} vs golden {golden['counts']['l1']}"
        )
        assert len(chunks.l2_chunks) == golden["counts"]["l2"], (
            f"L2 count: {len(chunks.l2_chunks)} vs golden {golden['counts']['l2']}"
        )
        assert len(chunks.l3_chunks) == golden["counts"]["l3"], (
            f"L3 count: {len(chunks.l3_chunks)} vs golden {golden['counts']['l3']}"
        )

        # Verify each L3 chunk
        actual_sorted = sorted(chunks.l3_chunks, key=lambda x: x.chunk_id)
        for actual, expected in zip(actual_sorted, golden["l3_chunks"]):
            assert actual.chunk_id == expected["chunk_id"], (
                f"Chunk ID mismatch: {actual.chunk_id} vs {expected['chunk_id']}"
            )
            assert actual.parent_section_id == expected["parent_section_id"], (
                f"Parent section mismatch for {actual.chunk_id}"
            )
            assert len(actual.content) == expected["content_length"], (
                f"Content length mismatch for {actual.chunk_id}: "
                f"{len(actual.content)} vs {expected['content_length']}"
            )
            assert count_tokens(actual.content) == expected["token_count"], (
                f"Token count mismatch for {actual.chunk_id}: "
                f"{count_tokens(actual.content)} vs {expected['token_count']}"
            )
            assert actual.content[:50] == expected["first_50_chars"], (
                f"Content prefix mismatch for {actual.chunk_id}"
            )
            assert actual.position.chapter == expected["position"]["chapter"]
            assert actual.position.section == expected["position"]["section"]
            assert actual.position.index == expected["position"]["index"]

    def test_all_content_preserved(self, tmp_path):
        """Every character of the original leaf content appears in some L3 chunk."""
        settings = _settings(tmp_path)
        structure = _build_golden_document()
        chunks = chunk_document(structure, settings)

        # Collect all leaf content
        leaf_contents = []
        for node in structure.root.walk():
            if node.content and node.level >= 2:
                leaf_contents.append(node.content)

        # Collect all L3 content
        all_l3_text = " ".join(c.content for c in chunks.l3_chunks)

        # Every sentence from input should appear in output
        for leaf in leaf_contents:
            sentences = [s.strip() for s in leaf.split(".") if s.strip()]
            for sentence in sentences:
                assert sentence in all_l3_text, f"Sentence lost during chunking: {sentence[:80]}..."

    def test_hierarchy_integrity(self, tmp_path):
        """Every L3 chunk references a valid L2 parent, every L2 references valid L1."""
        settings = _settings(tmp_path)
        structure = _build_golden_document()
        chunks = chunk_document(structure, settings)

        l2_ids = {c.chunk_id for c in chunks.l2_chunks}
        l1_ids = {c.chunk_id for c in chunks.l1_chunks}

        for c in chunks.l3_chunks:
            assert c.parent_section_id in l2_ids, (
                f"L3 {c.chunk_id} references non-existent L2 {c.parent_section_id}"
            )

        for c in chunks.l2_chunks:
            assert c.parent_chapter_id in l1_ids, (
                f"L2 {c.chunk_id} references non-existent L1 {c.parent_chapter_id}"
            )

    def test_chunk_ordering(self, tmp_path):
        """L3 chunks within the same section have monotonically increasing position indices."""
        settings = _settings(tmp_path)
        structure = _build_golden_document()
        chunks = chunk_document(structure, settings)

        from collections import defaultdict

        by_section: dict[str, list] = defaultdict(list)
        for c in chunks.l3_chunks:
            by_section[c.parent_section_id].append(c)

        for sec_id, sec_chunks in by_section.items():
            indices = [c.position.index for c in sec_chunks]
            assert indices == sorted(indices), (
                f"Non-monotonic indices in section {sec_id}: {indices}"
            )
            assert indices == list(range(len(indices))), (
                f"Indices not contiguous from 0 in section {sec_id}: {indices}"
            )

    def test_table_preservation(self, tmp_path):
        """Markdown tables in input must survive chunking intact."""
        settings = _settings(tmp_path)
        structure = _build_golden_document()
        chunks = chunk_document(structure, settings)

        # Find chunks from the comparison section (ch3-sec1)
        ch3_chunks = [c for c in chunks.l3_chunks if c.parent_section_id == "ch3-sec1"]
        all_ch3_text = " ".join(c.content for c in ch3_chunks)

        assert "BERT" in all_ch3_text, "Table row for BERT missing"
        assert "GPT-3" in all_ch3_text, "Table row for GPT-3 missing"
        assert "|" in all_ch3_text, "Table pipe separators stripped"
