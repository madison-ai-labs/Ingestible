"""Stage 3 — Smart Chunking.

Hierarchical semantic chunking that produces L0/L1/L2/L3 chunks.
Rules:
  - Never split mid-paragraph or mid-sentence
  - Tables and code blocks are atomic units
  - Target 250-500 tokens per L3 chunk with ~10% overlap
  - Dense content → smaller chunks, narrative → larger chunks
"""

from __future__ import annotations

import hashlib
import logging
from typing import TYPE_CHECKING

import numpy as np

from ingestible.config import Settings
from ingestible.models.chunks import (
    ChunkPosition,
    ChunkSet,
    L0Chunk,
    L1Chunk,
    L2Chunk,
    L3Chunk,
)
from ingestible.models.document import DocumentStructure, StructureNode
from ingestible.utils.text import (
    is_code_block,
    is_table_block,
    split_paragraphs,
    split_sentences,
)
from ingestible.utils.tokens import count_tokens

if TYPE_CHECKING:
    from ingestible.pipeline.stage5_embedding import Embedder

logger = logging.getLogger(__name__)


def chunk_document(
    structure: DocumentStructure,
    settings: Settings,
    embedder: Embedder | None = None,
) -> ChunkSet:
    """Build hierarchical chunks from a document structure tree."""
    doc_id = structure.doc_id
    root = structure.root

    l1_chunks: list[L1Chunk] = []
    l2_chunks: list[L2Chunk] = []
    l3_chunks: list[L3Chunk] = []

    # Walk the tree — level 1 children are chapters, level 2 are sections
    for ch_node in root.children:
        ch_id = ch_node.id

        section_ids: list[str] = []
        if ch_node.children:
            for sec_node in ch_node.children:
                sec_id = sec_node.id
                section_ids.append(sec_id)

                # Produce L3 chunks from section content
                passage_ids: list[str] = []
                if sec_node.children:
                    # Deeper nesting — treat sub-sections as content blocks
                    for sub in sec_node.children:
                        sub_passages = _split_into_passages(
                            sub.content, doc_id, ch_id, sub.id, settings, embedder
                        )
                        l3_chunks.extend(sub_passages)
                        passage_ids.extend(p.chunk_id for p in sub_passages)
                else:
                    passages = _split_into_passages(
                        sec_node.content, doc_id, ch_id, sec_id, settings, embedder
                    )
                    l3_chunks.extend(passages)
                    passage_ids.extend(p.chunk_id for p in passages)

                l2_chunks.append(
                    L2Chunk(
                        chunk_id=sec_id,
                        title=sec_node.title,
                        content=_truncate_for_summary(sec_node.content, 400),
                        page_start=sec_node.page_start,
                        page_end=sec_node.page_end,
                        parent_chapter_id=ch_id,
                        children_ids=passage_ids,
                    )
                )
        else:
            # No sub-sections — chunk chapter content directly
            passages = _split_into_passages(
                ch_node.content, doc_id, ch_id, ch_id, settings, embedder
            )
            l3_chunks.extend(passages)
            section_ids = [p.chunk_id for p in passages]

        l1_chunks.append(
            L1Chunk(
                chunk_id=ch_id,
                title=ch_node.title,
                content=_truncate_for_summary(ch_node.content, 500),
                page_start=ch_node.page_start,
                page_end=ch_node.page_end,
                children_ids=section_ids,
            )
        )

    # If the root itself has content and no children were generated
    if not l1_chunks and root.content:
        passages = _split_into_passages(
            root.content, doc_id, root.id, root.id, settings, embedder
        )
        l3_chunks.extend(passages)

    # Build L0
    toc_lines = []
    for c in l1_chunks:
        toc_lines.append(f"- {c.title}")
    toc_summary = "\n".join(toc_lines) if toc_lines else structure.title

    l0 = L0Chunk(
        chunk_id=f"{doc_id}-L0",
        title=structure.title,
        toc_summary=toc_summary,
        total_pages=root.page_end or 0,
        total_chapters=len(l1_chunks),
        total_sections=len(l2_chunks),
        total_passages=len(l3_chunks),
    )

    logger.info(
        "Chunking complete: %d chapters, %d sections, %d passages",
        len(l1_chunks),
        len(l2_chunks),
        len(l3_chunks),
    )

    return ChunkSet(
        doc_id=doc_id,
        l0=l0,
        l1_chunks=l1_chunks,
        l2_chunks=l2_chunks,
        l3_chunks=l3_chunks,
    )


def _split_into_passages(
    text: str,
    doc_id: str,
    chapter_id: str,
    section_id: str,
    settings: Settings,
    embedder: Embedder | None = None,
) -> list[L3Chunk]:
    """Split section text into L3 passage chunks respecting semantic boundaries."""
    if not text or not text.strip():
        return []

    if settings.chunking_strategy == "recursive":
        return _split_into_passages_recursive(
            text, doc_id, chapter_id, section_id, settings
        )

    if settings.chunking_strategy == "semantic" and embedder is not None:
        return _split_into_passages_semantic(
            text, doc_id, chapter_id, section_id, settings, embedder
        )

    paragraphs = split_paragraphs(text)
    if not paragraphs:
        return []

    max_tokens = settings.max_chunk_tokens
    min_tokens = settings.min_chunk_tokens
    overlap_frac = settings.chunk_overlap_fraction

    chunks: list[L3Chunk] = []
    current_paras: list[str] = []
    current_tokens = 0
    overlap_para: str | None = None

    for para in paragraphs:
        para_tokens = count_tokens(para)
        atomic = is_table_block(para) or is_code_block(para)

        # If this is an atomic block that exceeds max, emit it standalone
        if atomic and para_tokens > max_tokens:
            # Flush current buffer first
            if current_paras:
                chunks.append(
                    _make_l3(current_paras, doc_id, chapter_id, section_id, len(chunks))
                )
                current_paras = []
                current_tokens = 0
            chunks.append(
                _make_l3([para], doc_id, chapter_id, section_id, len(chunks))
            )
            overlap_para = None
            continue

        # Would adding this paragraph exceed the limit?
        if current_tokens + para_tokens > max_tokens and current_paras:
            chunks.append(
                _make_l3(current_paras, doc_id, chapter_id, section_id, len(chunks))
            )
            # Start new chunk with overlap
            overlap_para = current_paras[-1] if current_paras else None
            current_paras = []
            current_tokens = 0

            if overlap_para and count_tokens(overlap_para) < max_tokens * overlap_frac:
                current_paras.append(overlap_para)
                current_tokens = count_tokens(overlap_para)

        current_paras.append(para)
        current_tokens += para_tokens

    # Flush remainder
    if current_paras:
        # If the remainder is too small, merge with previous chunk
        if chunks and current_tokens < min_tokens:
            prev = chunks[-1]
            merged_content = prev.content + "\n\n" + "\n\n".join(current_paras)
            chunks[-1] = prev.model_copy(update={"content": merged_content})
        else:
            chunks.append(
                _make_l3(current_paras, doc_id, chapter_id, section_id, len(chunks))
            )

    # Label positions
    for i, chunk in enumerate(chunks):
        if len(chunks) == 1:
            chunk.position_in_section = "only"
        elif i == 0:
            chunk.position_in_section = "first"
        elif i == len(chunks) - 1:
            chunk.position_in_section = "last"
        else:
            chunk.position_in_section = "middle"

    return chunks


def _make_l3(
    paras: list[str],
    doc_id: str,
    chapter_id: str,
    section_id: str,
    index: int,
) -> L3Chunk:
    content = "\n\n".join(paras)
    h = hashlib.md5(content.encode()).hexdigest()[:8]
    chunk_id = f"{doc_id}-{section_id}-p{index}-{h}"
    return L3Chunk(
        chunk_id=chunk_id,
        content=content,
        content_hash=hashlib.md5(content.encode()).hexdigest(),
        parent_section_id=section_id,
        position=ChunkPosition(chapter=chapter_id, section=section_id, index=index),
    )


def _truncate_for_summary(text: str, max_tokens: int) -> str:
    """Truncate text to roughly max_tokens for use in L1/L2 content fields."""
    if not text:
        return ""
    tokens = count_tokens(text)
    if tokens <= max_tokens:
        return text
    # Rough char-based truncation (approx 4 chars/token)
    max_chars = max_tokens * 4
    return text[:max_chars] + "..."


# ---------------------------------------------------------------------------
# Recursive character splitting
# ---------------------------------------------------------------------------

_RECURSIVE_SEPARATORS = ["\n\n", "\n", ". ", " "]


def _split_into_passages_recursive(
    text: str,
    doc_id: str,
    chapter_id: str,
    section_id: str,
    settings: Settings,
) -> list[L3Chunk]:
    """Split using separator hierarchy: \\n\\n → \\n → '. ' → ' '."""
    max_tokens = settings.max_chunk_tokens
    min_tokens = settings.min_chunk_tokens
    overlap_frac = settings.chunk_overlap_fraction

    raw_pieces = _recursive_split(text, _RECURSIVE_SEPARATORS, max_tokens)

    # Apply overlap between consecutive chunks
    if overlap_frac > 0 and len(raw_pieces) > 1:
        raw_pieces = _apply_recursive_overlap(raw_pieces, max_tokens, overlap_frac)

    # Merge too-small trailing piece into previous
    if len(raw_pieces) > 1 and count_tokens(raw_pieces[-1]) < min_tokens:
        raw_pieces[-2] = raw_pieces[-2] + "\n\n" + raw_pieces[-1]
        raw_pieces.pop()

    chunks: list[L3Chunk] = []
    for i, piece in enumerate(raw_pieces):
        if not piece.strip():
            continue
        chunks.append(_make_l3([piece], doc_id, chapter_id, section_id, len(chunks)))

    # Label positions
    for i, chunk in enumerate(chunks):
        if len(chunks) == 1:
            chunk.position_in_section = "only"
        elif i == 0:
            chunk.position_in_section = "first"
        elif i == len(chunks) - 1:
            chunk.position_in_section = "last"
        else:
            chunk.position_in_section = "middle"

    return chunks


def _recursive_split(
    text: str,
    separators: list[str],
    max_tokens: int,
) -> list[str]:
    """Recursively split text using a hierarchy of separators."""
    if not text.strip():
        return []

    if count_tokens(text) <= max_tokens:
        return [text.strip()]

    if not separators:
        # No more separators — hard split at approximate character boundary
        logger.warning("Hard-splitting chunk at char boundary (%d tokens)", count_tokens(text))
        approx_chars = max_tokens * 4  # rough estimate
        pieces = []
        while text:
            pieces.append(text[:approx_chars].strip())
            text = text[approx_chars:]
        return [p for p in pieces if p]

    sep = separators[0]
    remaining_seps = separators[1:]

    parts = text.split(sep)
    # Re-attach separator to end of each part (except last) if it's not whitespace-only
    if sep not in ("\n\n", "\n"):
        parts = [
            parts[i] + sep if i < len(parts) - 1 else parts[i]
            for i in range(len(parts))
        ]

    result: list[str] = []
    current = ""

    for part in parts:
        candidate = (current + sep + part) if current else part
        if current and count_tokens(candidate) > max_tokens:
            # Flush current
            if count_tokens(current) <= max_tokens:
                result.append(current.strip())
            else:
                # Current itself is too big — recurse with finer separator
                result.extend(_recursive_split(current, remaining_seps, max_tokens))
            current = part
        else:
            current = candidate

    # Flush remainder
    if current.strip():
        if count_tokens(current) <= max_tokens:
            result.append(current.strip())
        else:
            result.extend(_recursive_split(current, remaining_seps, max_tokens))

    return [r for r in result if r]


def _apply_recursive_overlap(
    pieces: list[str], max_tokens: int, overlap_frac: float
) -> list[str]:
    """Prepend tail text from previous piece to the start of each subsequent piece."""
    overlap_budget = int(max_tokens * overlap_frac)
    if overlap_budget <= 0:
        return pieces

    result = [pieces[0]]
    for i in range(1, len(pieces)):
        prev = pieces[i - 1]
        # Take up to overlap_budget tokens from end of previous piece
        words = prev.split()
        overlap_words: list[str] = []
        token_count = 0
        for w in reversed(words):
            wt = count_tokens(w)
            if token_count + wt > overlap_budget:
                break
            overlap_words.insert(0, w)
            token_count += wt

        if overlap_words:
            overlap_text = " ".join(overlap_words)
            candidate = overlap_text + " " + pieces[i]
            # Only add overlap if total doesn't exceed max_tokens
            if count_tokens(candidate) <= max_tokens:
                result.append(candidate)
            else:
                result.append(pieces[i])
        else:
            result.append(pieces[i])

    return result


# ---------------------------------------------------------------------------
# Semantic chunking
# ---------------------------------------------------------------------------


def _split_into_passages_semantic(
    text: str,
    doc_id: str,
    chapter_id: str,
    section_id: str,
    settings: Settings,
    embedder: Embedder,
) -> list[L3Chunk]:
    """Split text into L3 chunks using embedding-based semantic similarity."""
    paragraphs = split_paragraphs(text)
    if not paragraphs:
        return []

    max_tokens = settings.max_chunk_tokens
    min_tokens = settings.min_chunk_tokens

    # Separate atomic blocks (tables, code) from prose paragraphs.
    # Track original positions so we can re-insert them later.
    prose_parts: list[str] = []           # prose paragraph text
    atomic_blocks: list[tuple[int, str]] = []  # (original para index, text)

    for i, para in enumerate(paragraphs):
        if is_table_block(para) or is_code_block(para):
            atomic_blocks.append((i, para))
        else:
            prose_parts.append(para)

    # Split prose into sentences
    sentences: list[str] = []
    for para in prose_parts:
        sents = split_sentences(para)
        sentences.extend(sents)

    if not sentences:
        # Only atomic blocks — emit each as standalone chunk
        chunks: list[L3Chunk] = []
        for _, block in atomic_blocks:
            chunks.append(_make_l3([block], doc_id, chapter_id, section_id, len(chunks)))
        return chunks

    # Group sentences by semantic similarity
    groups = _semantic_group_sentences(sentences, embedder, settings)

    # Build chunks from groups, re-inserting atomic blocks at approximate positions
    chunks = []
    # Emit prose groups as chunks
    for group in groups:
        chunks.append(
            _make_l3(group, doc_id, chapter_id, section_id, len(chunks))
        )

    # Insert atomic blocks as standalone chunks
    # Place them proportionally based on their original position in the paragraph list
    for orig_idx, block in atomic_blocks:
        # Approximate insertion: ratio of original position to total paragraphs
        ratio = orig_idx / max(len(paragraphs), 1)
        insert_pos = min(int(ratio * len(chunks)) + 1, len(chunks))
        chunks.insert(
            insert_pos,
            _make_l3([block], doc_id, chapter_id, section_id, insert_pos),
        )

    # Re-index chunk IDs after insertions
    for i, chunk in enumerate(chunks):
        content = chunk.content
        h = hashlib.md5(content.encode()).hexdigest()[:8]
        chunk.chunk_id = f"{doc_id}-{section_id}-p{i}-{h}"
        chunk.content_hash = hashlib.md5(content.encode()).hexdigest()
        chunk.position = ChunkPosition(chapter=chapter_id, section=section_id, index=i)

    # Label positions
    for i, chunk in enumerate(chunks):
        if len(chunks) == 1:
            chunk.position_in_section = "only"
        elif i == 0:
            chunk.position_in_section = "first"
        elif i == len(chunks) - 1:
            chunk.position_in_section = "last"
        else:
            chunk.position_in_section = "middle"

    return chunks


def _semantic_group_sentences(
    sentences: list[str],
    embedder: Embedder,
    settings: Settings,
) -> list[list[str]]:
    """Group sentences into semantically coherent chunks using embedding similarity."""
    if len(sentences) <= 1:
        return [sentences] if sentences else []

    max_tokens = settings.max_chunk_tokens
    min_tokens = settings.min_chunk_tokens
    percentile = settings.semantic_threshold_percentile

    # Embed all sentences
    embeddings = embedder.embed_passages(sentences)
    emb_array = np.array(embeddings)  # shape: (n, dim)

    # Cosine similarity between consecutive sentences (already normalized → dot product)
    similarities = np.sum(emb_array[:-1] * emb_array[1:], axis=1)

    # Find breakpoints: where similarity drops below the threshold percentile
    threshold = float(np.percentile(similarities, percentile))

    groups: list[list[str]] = []
    current_group: list[str] = [sentences[0]]
    current_tokens = count_tokens(sentences[0])

    for i in range(1, len(sentences)):
        sent_tokens = count_tokens(sentences[i])
        sim = similarities[i - 1]

        # Force break if we'd exceed max tokens
        would_exceed = (current_tokens + sent_tokens) > max_tokens
        # Semantic break if similarity is below threshold AND we have enough tokens
        semantic_break = sim < threshold and current_tokens >= min_tokens

        if would_exceed or semantic_break:
            groups.append(current_group)
            current_group = [sentences[i]]
            current_tokens = sent_tokens
        else:
            current_group.append(sentences[i])
            current_tokens += sent_tokens

    # Flush remainder
    if current_group:
        # If too small, merge with previous group
        if groups and current_tokens < min_tokens:
            groups[-1].extend(current_group)
        else:
            groups.append(current_group)

    # Apply sentence overlap between groups
    overlap_frac = settings.chunk_overlap_fraction
    if overlap_frac > 0 and len(groups) > 1:
        groups = _apply_sentence_overlap(groups, max_tokens, overlap_frac)

    return groups


def _apply_sentence_overlap(
    groups: list[list[str]],
    max_tokens: int,
    overlap_frac: float,
) -> list[list[str]]:
    """Prepend last 1-2 sentences from previous group to next, respecting max_tokens."""
    overlap_budget = int(max_tokens * overlap_frac)
    if overlap_budget <= 0:
        return groups

    result = [groups[0]]
    for i in range(1, len(groups)):
        prev = groups[i - 1]
        # Take up to 2 sentences from end of previous group
        candidates = prev[-2:] if len(prev) >= 2 else prev[-1:]
        overlap_sents: list[str] = []
        token_count = 0
        for sent in candidates:
            st = count_tokens(sent)
            if token_count + st > overlap_budget:
                break
            overlap_sents.append(sent)
            token_count += st

        if overlap_sents:
            new_group = overlap_sents + groups[i]
            # Verify total doesn't exceed max_tokens
            total = sum(count_tokens(s) for s in new_group)
            if total <= max_tokens:
                result.append(new_group)
            else:
                result.append(groups[i])
        else:
            result.append(groups[i])

    return result
