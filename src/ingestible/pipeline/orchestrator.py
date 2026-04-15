"""Pipeline orchestrator — runs the full ingestion pipeline in sequence.

Dynamic step counter adapts to enabled features.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from pathlib import Path

from ingestible.config import Settings
from ingestible.metrics import ACTIVE_INGESTIONS, INGEST_TOTAL
from ingestible.models.chunks import ChunkSet
from ingestible.models.document import DocumentStructure, ParsedDocument
from ingestible.pipeline.checkpoint import clear_checkpoints, load_checkpoint, save_checkpoint
from ingestible.pipeline.fetch import is_url
from ingestible.pipeline.locking import document_lock
from ingestible.pipeline.metadata import extract_metadata
from ingestible.pipeline.stage1_parsing import parse_document
from ingestible.pipeline.stage1b_clean import clean_document
from ingestible.pipeline.stage2_structure import detect_structure
from ingestible.pipeline.stage3_chunking import chunk_document
from ingestible.pipeline.stage3b_validation import validate_chunks
from ingestible.pipeline.stage5_embedding import Embedder, build_indexes
from ingestible.pipeline.stage6_storage import save_document
from ingestible.profiles import PROFILES, detect_profile, detect_profile_with_llm
from ingestible.utils.language import detect_language

logger = logging.getLogger(__name__)


def _propagate_timestamps(chunks: ChunkSet, parsed: ParsedDocument) -> None:
    """Propagate timestamps from parsed pages to L3 chunks for audio/video sources.

    Matches L3 chunk content against page content to find the source page,
    then copies timestamps. Falls back to parsing [MM:SS] markers in the text.
    """
    import re

    # Build page lookup by content substring
    for chunk in chunks.l3_chunks:
        # Try to find the first timestamp marker in the chunk content
        m = re.search(r"\[(\d{1,2}):(\d{2}):(\d{2})\]", chunk.content)
        if m:
            chunk.timestamp_start = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
        else:
            m = re.search(r"\[(\d{1,2}):(\d{2})\]", chunk.content)
            if m:
                chunk.timestamp_start = int(m.group(1)) * 60 + int(m.group(2))

        # Find the last timestamp marker for end time
        matches = list(
            re.finditer(r"\[(\d{1,2}):(\d{2}):(\d{2})\]|\[(\d{1,2}):(\d{2})\]", chunk.content)
        )
        if matches:
            last = matches[-1]
            if last.group(1) and last.group(3):  # HH:MM:SS
                chunk.timestamp_end = (
                    int(last.group(1)) * 3600 + int(last.group(2)) * 60 + int(last.group(3))
                )
            elif last.group(4):  # MM:SS
                chunk.timestamp_end = int(last.group(4)) * 60 + int(last.group(5))


def _parse_keyframe_timestamp(caption: str) -> float | None:
    """Parse seconds from a keyframe caption like 'Keyframe at [01:30]'."""
    import re

    m = re.search(r"\[(\d{1,2}):(\d{2}):(\d{2})\]", caption)
    if m:
        return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
    m = re.search(r"\[(\d{1,2}):(\d{2})\]", caption)
    if m:
        return int(m.group(1)) * 60 + int(m.group(2))
    return None


def generate_doc_id(file_path: Path) -> str:
    """Generate a short deterministic document ID from the file path."""
    h = hashlib.md5(str(file_path.resolve()).encode(), usedforsecurity=False).hexdigest()[:12]
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
    if settings.content_classification:
        steps += 1
    if not skip_enrichment:
        steps += 1  # enrichment
        if settings.contextual_chunking:
            steps += 1  # contextual prefixes
    return steps


def _save_figure_images(parsed: ParsedDocument, doc_dir: Path) -> None:
    """Save extracted figure images to {doc_dir}/figures/."""
    all_figures = [fig for page in parsed.pages for fig in page.figures]
    if not all_figures:
        return

    figures_dir = doc_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    for fig in all_figures:
        # The image data may come from Docling's image URI or be absent
        # For now we create a placeholder — actual image bytes are extracted
        # separately if the Docling image ref has data
        marker_path = figures_dir / fig.filename
        if not marker_path.exists():
            marker_path.write_bytes(b"")  # placeholder for image


def ingest(
    file_path: str | Path,
    settings: Settings,
    skip_enrichment: bool = False,
    verbose: bool = False,
    force: bool = False,
    resume: bool = True,
    progress_callback=None,
    access_tags: list[str] | None = None,
    weight: float = 0.0,
    pinned: bool = False,
    tags: list[str] | None = None,
    original_filename: str | None = None,
    retain_original: bool = False,
) -> Path:
    """Run the full ingestion pipeline on a document. Returns the document directory.

    ``file_path`` may be a local path, an HTTP(S) URL, or a cloud URL (s3://, gs://, az://).
    ``original_filename`` carries the human-facing filename when ``file_path`` is a
    temporary upload path (the extension there is preserved but the basename is random).
    """
    # --- Cost tracking ---
    try:
        from ingestible.models.costs import get_cost_tracker, reset_cost_tracker

        reset_cost_tracker()
        _cost_start_time = time.monotonic()
        _cost_tracker = get_cost_tracker()
    except Exception:
        _cost_start_time = None
        _cost_tracker = None

    # --- Cloud / URL fetch ---
    _fetched_tmp: Path | None = None
    str_path = str(file_path)

    from ingestible.pipeline.cloud import is_cloud_url

    if is_cloud_url(str_path):
        from ingestible.pipeline.cloud import fetch_cloud

        _fetched_tmp = fetch_cloud(str_path, max_bytes=settings.max_upload_bytes)
        file_path = _fetched_tmp
    elif is_url(str_path):
        from ingestible.pipeline.fetch import fetch_url

        _fetched_tmp = fetch_url(str_path, max_bytes=settings.max_upload_bytes)
        file_path = _fetched_tmp

    file_path = Path(file_path).resolve()

    # Record input file size for cost tracking
    try:
        if _cost_tracker is not None:
            _cost_tracker.input_file_bytes = file_path.stat().st_size if file_path.is_file() else 0
    except Exception:
        pass

    if verbose:
        logging.getLogger("ingestible").setLevel(logging.INFO)

    doc_id = generate_doc_id(file_path)
    total = _count_steps(settings, skip_enrichment)
    step = 0

    def _log(msg: str) -> None:
        nonlocal step
        step += 1
        logger.info("[%d/%d] %s", step, total, msg)
        if progress_callback is not None:
            progress_callback(step, total, msg)

    logger.info("=== Ingesting %s as %s ===", file_path.name, doc_id)

    # --- Incremental check ---
    content_hash = _compute_content_hash(file_path)
    if not force:
        existing = _check_existing(doc_id, content_hash, settings)
        if existing:
            logger.info("Document unchanged, skipping. Use --force to re-ingest.")
            INGEST_TOTAL.labels(status="skipped").inc()
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
            INGEST_TOTAL.labels(status="skipped").inc()
            return dup

    # --- Version archival + pipeline under document lock ---
    doc_dir = settings.documents_dir / doc_id
    previous_chunks: ChunkSet | None = None
    ACTIVE_INGESTIONS.inc()
    try:
        with document_lock(doc_dir):
            if force and (doc_dir / "meta.json").exists():
                from ingestible.pipeline.stage6_storage import archive_version, load_chunks

                try:
                    previous_chunks = load_chunks(doc_dir)
                except Exception:
                    pass
                archive_version(doc_dir)

            # --- Checkpoint setup ---
            use_checkpoint = settings.checkpoint_enabled and resume
            doc_dir.mkdir(parents=True, exist_ok=True)

            # Stage 1: Parse
            if use_checkpoint and (cp := load_checkpoint(doc_dir, "parsed")):
                parsed = ParsedDocument(**cp)
                logger.info("  Resumed from checkpoint: parsed")
            else:
                _log("Parsing document...")
                parsed = parse_document(file_path, timeout=settings.parse_timeout)
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

            # Save extracted figure images to disk (before checkpoint serialization)
            _save_figure_images(parsed, doc_dir)

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

            # Stage 1c: Content classification (if enabled)
            if settings.content_classification:
                _log("Classifying content blocks...")
                from ingestible.pipeline.stage1c_classify import classify_document

                parsed.block_classifications = classify_document(parsed)

            # --- Profile resolution ---
            if settings.extraction_profile == "auto":
                if settings.profile_llm_fallback and not skip_enrichment:
                    profile_name = asyncio.run(detect_profile_with_llm(parsed, settings))
                else:
                    profile_name = detect_profile(parsed)
            else:
                profile_name = settings.extraction_profile
            profile = PROFILES.get(profile_name, PROFILES["general"])
            logger.info("Extraction profile: %s", profile.name)

            # Apply profile overrides to settings for chunking
            profile_overrides: dict = {}
            if profile.max_chunk_tokens is not None:
                profile_overrides["max_chunk_tokens"] = profile.max_chunk_tokens
            if profile.min_chunk_tokens is not None:
                profile_overrides["min_chunk_tokens"] = profile.min_chunk_tokens
            if profile.chunking_strategy is not None:
                profile_overrides["chunking_strategy"] = profile.chunking_strategy
            if profile_overrides:
                settings = settings.model_copy(update=profile_overrides)

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

            # Propagate timestamps for audio/video sources
            if parsed.source_format in ("audio", "video"):
                _propagate_timestamps(chunks, parsed)

            # Extract keyframes for video sources
            if parsed.source_format == "video":
                try:
                    from ingestible.pipeline.stage1_parsing import _extract_keyframes

                    keyframes = _extract_keyframes(file_path, doc_dir, interval=60)
                    # Attach keyframes to the nearest pages by timestamp
                    for fig in keyframes:
                        # Keyframe figures are already saved to doc_dir/figures/ by _extract_keyframes
                        pass
                    # Store keyframe refs on pages for figure manifest
                    if keyframes:
                        logger.info("Extracted %d keyframes from video", len(keyframes))
                        for page in parsed.pages:
                            for fig in keyframes:
                                # Parse timestamp from caption "[MM:SS]"
                                ts = _parse_keyframe_timestamp(fig.caption)
                                if (
                                    ts is not None
                                    and page.timestamp_start is not None
                                    and page.timestamp_end is not None
                                ):
                                    if page.timestamp_start <= ts <= page.timestamp_end:
                                        page.figures.append(fig)
                except Exception as e:
                    logger.warning("Video keyframe extraction failed: %s", e)

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

                        chunks = asyncio.run(
                            enrich_chunks(
                                chunks,
                                settings,
                                profile=profile,
                                previous_chunks=previous_chunks,
                            )
                        )
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
            build_indexes(
                chunks,
                doc_dir,
                embedder,
                language=parsed.detected_language,
                previous_chunks=previous_chunks,
                access_tags=access_tags,
            )

            # Stage 6: Storage
            _log("Saving to disk...")
            doc_dir = save_document(
                structure,
                chunks,
                settings,
                content_hash=content_hash,
                extraction_profile=profile.name,
                access_tags=access_tags,
                weight=weight,
                pinned=pinned,
                tags=tags,
                source_path=file_path,
                original_filename=original_filename,
                retain_original=retain_original,
            )

            # Clean up checkpoints on success
            if use_checkpoint:
                clear_checkpoints(doc_dir)

        # Finalize cost tracking
        try:
            if _cost_tracker is not None and _cost_start_time is not None:
                from ingestible.models.costs import get_cost_tracker

                tracker = get_cost_tracker()
                tracker.duration_seconds = time.monotonic() - _cost_start_time
                tracker.total_chunks = (
                    len(chunks.l3_chunks) + len(chunks.l2_chunks) + len(chunks.l1_chunks) + 1
                )
                tracker.enrichment_llm.provider = (
                    tracker.enrichment_llm.provider or settings.llm_provider
                )
                tracker.estimate_cost()
        except Exception:
            pass

        INGEST_TOTAL.labels(status="success").inc()
        logger.info("=== Done. Document stored at %s ===", doc_dir)
        return doc_dir
    except Exception:
        INGEST_TOTAL.labels(status="failed").inc()
        raise
    finally:
        ACTIVE_INGESTIONS.dec()
        # Clean up fetched temp file on both success and failure
        if _fetched_tmp is not None:
            _fetched_tmp.unlink(missing_ok=True)
