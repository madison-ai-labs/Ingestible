"""Pipeline orchestrator — runs the full ingestion pipeline in sequence.

Dynamic step counter adapts to enabled features.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from pathlib import Path

from ingestible.config import Settings
from ingestible.models.chunks import ChunkSet
from ingestible.models.document import DocumentStructure, ParsedDocument
from ingestible.pipeline.stage1_parsing import parse_document
from ingestible.pipeline.stage1b_clean import clean_document
from ingestible.pipeline.stage2_structure import detect_structure
from ingestible.pipeline.stage3_chunking import chunk_document
from ingestible.pipeline.stage3b_validation import validate_chunks
from ingestible.pipeline.checkpoint import clear_checkpoints, load_checkpoint, save_checkpoint
from ingestible.pipeline.fetch import is_url
from ingestible.pipeline.metadata import extract_metadata
from ingestible.pipeline.stage5_embedding import Embedder, build_indexes
from ingestible.utils.language import detect_language
from ingestible.pipeline.stage6_storage import save_document

logger = logging.getLogger(__name__)


def generate_doc_id(file_path: Path) -> str:
    """Generate a short deterministic document ID from the file path."""
    h = hashlib.md5(str(file_path.resolve()).encode()).hexdigest()[:12]
    stem = file_path.stem[:30].lower().replace(" ", "-")
    return f"{stem}-{h}"


def _compute_content_hash(file_path: Path) -> str:
    """SHA-256 of file bytes, read in 8KB chunks."""
    sha = hashlib.sha256()
    with open(file_path, "rb") as f:
        while True:
            data = f.read(8192)
            if not data:
                break
            sha.update(data)
    return sha.hexdigest()


def _check_existing(doc_id: str, content_hash: str, settings: Settings) -> Path | None:
    """If a doc with this id already has the same content_hash, return its dir."""
    doc_dir = settings.documents_dir / doc_id
    meta_path = doc_dir / "meta.json"
    if not meta_path.exists():
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta.get("content_hash") == content_hash and content_hash:
            return doc_dir
    except (json.JSONDecodeError, OSError):
        pass
    return None


def _check_duplicate_content(
    content_hash: str, current_doc_id: str, settings: Settings
) -> Path | None:
    """Scan all meta.json for matching content_hash from a different doc_id."""
    docs_dir = settings.documents_dir
    if not docs_dir.exists():
        return None
    for d in docs_dir.iterdir():
        if not d.is_dir() or d.name == current_doc_id:
            continue
        meta_path = d / "meta.json"
        if not meta_path.exists():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if meta.get("content_hash") == content_hash and content_hash:
                return d
        except (json.JSONDecodeError, OSError):
            continue
    return None


def _count_steps(settings: Settings, skip_enrichment: bool) -> int:
    """Compute total pipeline steps based on enabled features."""
    # Always: parse, structure, chunk, validate, embed, save = 6
    steps = 6
    if settings.cleaning_enabled:
        steps += 1
    if not skip_enrichment:
        steps += 1  # enrichment
        if settings.contextual_chunking:
            steps += 1  # contextual prefixes
    return steps


def ingest(
    file_path: str | Path,
    settings: Settings,
    skip_enrichment: bool = False,
    verbose: bool = False,
    force: bool = False,
    resume: bool = True,
) -> Path:
    """Run the full ingestion pipeline on a document. Returns the document directory.

    ``file_path`` may be a local path **or** an HTTP(S) URL.
    """
    # --- URL fetch ---
    _fetched_tmp: Path | None = None
    if is_url(str(file_path)):
        from ingestible.pipeline.fetch import fetch_url

        _fetched_tmp = fetch_url(str(file_path))
        file_path = _fetched_tmp

    file_path = Path(file_path).resolve()

    if verbose:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    else:
        logging.basicConfig(level=logging.WARNING)

    doc_id = generate_doc_id(file_path)
    total = _count_steps(settings, skip_enrichment)
    step = 0

    def _log(msg: str) -> None:
        nonlocal step
        step += 1
        logger.info("[%d/%d] %s", step, total, msg)

    logger.info("=== Ingesting %s as %s ===", file_path.name, doc_id)

    # --- Incremental check ---
    content_hash = _compute_content_hash(file_path)
    if not force:
        existing = _check_existing(doc_id, content_hash, settings)
        if existing:
            logger.info("Document unchanged, skipping. Use --force to re-ingest.")
            return existing

    # --- Dedup check ---
    if settings.dedup_enabled and not force:
        dup = _check_duplicate_content(content_hash, doc_id, settings)
        if dup:
            logger.warning(
                "Duplicate: %s matches existing document at %s. Skipping.",
                file_path.name,
                dup.name,
            )
            return dup

    # --- Checkpoint setup ---
    use_checkpoint = settings.checkpoint_enabled and resume
    doc_dir = settings.documents_dir / doc_id
    doc_dir.mkdir(parents=True, exist_ok=True)

    # Stage 1: Parse
    if use_checkpoint and (cp := load_checkpoint(doc_dir, "parsed")):
        parsed = ParsedDocument(**cp)
        logger.info("  Resumed from checkpoint: parsed")
    else:
        _log("Parsing document...")
        parsed = parse_document(file_path)
        # Extract file-level metadata and attach to parsed document
        meta_info = extract_metadata(file_path)
        parsed.metadata = meta_info
        if meta_info.language:
            parsed.detected_language = meta_info.language
        # Detect language from content if not already set
        if not parsed.detected_language or parsed.detected_language == "en":
            detected = detect_language(parsed.full_markdown)
            if detected:
                parsed.detected_language = detected
        if use_checkpoint:
            save_checkpoint(doc_dir, "parsed", parsed)

    # Stage 1b: Clean (if enabled)
    if settings.cleaning_enabled:
        if use_checkpoint and (cp := load_checkpoint(doc_dir, "cleaned")):
            parsed = ParsedDocument(**cp)
            logger.info("  Resumed from checkpoint: cleaned")
        else:
            _log("Cleaning document...")
            parsed = clean_document(parsed)
            if use_checkpoint:
                save_checkpoint(doc_dir, "cleaned", parsed)

    # Stage 2: Structure detection
    if use_checkpoint and (cp := load_checkpoint(doc_dir, "structure")):
        structure = DocumentStructure(**cp)
        logger.info("  Resumed from checkpoint: structure")
    else:
        _log("Detecting structure...")
        structure = detect_structure(parsed, doc_id)
        if use_checkpoint:
            save_checkpoint(doc_dir, "structure", structure)

    # Stage 3: Chunking + Stage 3b: Validation
    embedder: Embedder | None = None
    if use_checkpoint and (cp := load_checkpoint(doc_dir, "validated")):
        chunks = ChunkSet(**cp)
        logger.info("  Resumed from checkpoint: validated")
    else:
        _log("Chunking...")
        if settings.chunking_strategy == "semantic":
            embedder = Embedder(settings)
        chunks = chunk_document(structure, settings, embedder=embedder)

        # Stage 3b: Validation
        _log("Validating chunks...")
        chunks, quality_report = validate_chunks(chunks)
        if use_checkpoint:
            save_checkpoint(doc_dir, "validated", chunks)

    # Populate L0 metadata from parsed document
    if parsed.metadata:
        if parsed.metadata.author and not chunks.l0.author:
            chunks.l0.author = parsed.metadata.author
        if parsed.metadata.creation_date:
            chunks.l0.creation_date = parsed.metadata.creation_date
        if parsed.detected_language:
            chunks.l0.source_language = parsed.detected_language

    # Stage 3c: Contextual chunking (if enabled + not skip_enrichment)
    if settings.contextual_chunking and not skip_enrichment:
        if use_checkpoint and (cp := load_checkpoint(doc_dir, "contextual")):
            chunks = ChunkSet(**cp)
            logger.info("  Resumed from checkpoint: contextual")
        else:
            _log("Adding contextual prefixes...")
            try:
                from ingestible.pipeline.stage3c_contextual import add_context_prefixes

                chunks = asyncio.run(add_context_prefixes(chunks, structure, settings))
                if use_checkpoint:
                    save_checkpoint(doc_dir, "contextual", chunks)
            except Exception as e:
                logger.warning("Contextual chunking failed, continuing without it: %s", e)

    # Stage 4: Enrichment (optional)
    if not skip_enrichment:
        if use_checkpoint and (cp := load_checkpoint(doc_dir, "enriched")):
            chunks = ChunkSet(**cp)
            logger.info("  Resumed from checkpoint: enriched")
        else:
            _log("LLM enrichment...")
            try:
                from ingestible.pipeline.stage4_enrichment import enrich_chunks

                chunks = asyncio.run(enrich_chunks(chunks, settings))
                if use_checkpoint:
                    save_checkpoint(doc_dir, "enriched", chunks)
            except Exception as e:
                logger.warning("Enrichment failed, continuing without it: %s", e)
    else:
        logger.info("  Skipping enrichment (--skip-enrichment)")

    # Stage 5: Embedding & indexing
    _log("Building indexes...")
    if embedder is None:
        embedder = Embedder(settings)
    build_indexes(chunks, doc_dir, embedder, language=parsed.detected_language)

    # Stage 6: Storage
    _log("Saving to disk...")
    doc_dir = save_document(structure, chunks, settings, content_hash=content_hash)

    # Clean up checkpoints on success
    if use_checkpoint:
        clear_checkpoints(doc_dir)

    # Clean up fetched temp file
    if _fetched_tmp is not None:
        _fetched_tmp.unlink(missing_ok=True)

    logger.info("=== Done. Document stored at %s ===", doc_dir)
    return doc_dir
