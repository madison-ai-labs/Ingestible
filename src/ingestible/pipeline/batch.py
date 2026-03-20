"""Batch/directory ingestion — discover supported files and ingest with error isolation."""

from __future__ import annotations

import logging
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

from ingestible.config import Settings
from ingestible.pipeline.stage1_parsing import SUPPORTED_FORMATS

logger = logging.getLogger(__name__)


@dataclass
class FileResult:
    path: Path
    doc_id: str | None = None
    doc_dir: Path | None = None
    error: str | None = None
    skipped: bool = False
    elapsed_seconds: float = 0.0


@dataclass
class BatchReport:
    total: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0
    elapsed_seconds: float = 0.0
    results: list[FileResult] = field(default_factory=list)


def discover_files(
    path: str | Path,
    recursive: bool = True,
) -> list[Path]:
    """Discover supported files from a path (file, directory, or glob pattern).

    - Single file: returns [file] if supported
    - Directory: scans for supported files (recursive by default)
    - Glob string containing * or ?: expands via Path.glob
    """
    path_str = str(path)

    # Glob pattern
    if "*" in path_str or "?" in path_str:
        base = Path(".")
        # If pattern has a non-glob prefix, use it as base
        parts = Path(path_str).parts
        base_parts = []
        for p in parts:
            if "*" in p or "?" in p:
                break
            base_parts.append(p)
        if base_parts:
            base = Path(*base_parts)
            pattern = str(Path(*parts[len(base_parts) :]))
        else:
            pattern = path_str

        files = sorted(
            f for f in base.glob(pattern) if f.is_file() and f.suffix.lower() in SUPPORTED_FORMATS
        )
        return files

    p = Path(path).resolve()

    # Single file
    if p.is_file():
        if p.suffix.lower() in SUPPORTED_FORMATS:
            return [p]
        return []

    # Directory
    if p.is_dir():
        if recursive:
            files = sorted(
                f for f in p.rglob("*") if f.is_file() and f.suffix.lower() in SUPPORTED_FORMATS
            )
        else:
            files = sorted(
                f for f in p.iterdir() if f.is_file() and f.suffix.lower() in SUPPORTED_FORMATS
            )
        return files

    return []


def _ingest_one(
    file_path: Path,
    settings: Settings,
    skip_enrichment: bool,
    force: bool,
) -> FileResult:
    """Ingest a single file with error isolation. Runs in-process."""
    from ingestible.pipeline.orchestrator import generate_doc_id, ingest

    start = time.monotonic()
    try:
        doc_dir = ingest(
            file_path,
            settings,
            skip_enrichment=skip_enrichment,
            force=force,
        )
        elapsed = time.monotonic() - start
        doc_id = generate_doc_id(file_path)

        # Detect if it was skipped (unchanged/duplicate) by checking elapsed time
        # A real ingest takes at least a few seconds; a skip returns instantly
        return FileResult(
            path=file_path,
            doc_id=doc_id,
            doc_dir=doc_dir,
            elapsed_seconds=round(elapsed, 2),
        )
    except Exception as e:
        elapsed = time.monotonic() - start
        logger.error("Failed to ingest %s: %s", file_path.name, e)
        return FileResult(
            path=file_path,
            error=str(e),
            elapsed_seconds=round(elapsed, 2),
        )


def ingest_batch(
    path: str | Path,
    settings: Settings,
    skip_enrichment: bool = False,
    force: bool = False,
    parallel: int = 1,
    recursive: bool = True,
) -> BatchReport:
    """Discover and ingest all supported files from a path.

    Args:
        path: File, directory, or glob pattern.
        settings: Pipeline settings.
        skip_enrichment: Skip LLM enrichment for all files.
        force: Force re-ingestion even if unchanged.
        parallel: Number of parallel workers (1 = sequential).
        recursive: Recurse into subdirectories.

    Returns:
        BatchReport with per-file results.
    """
    files = discover_files(path, recursive=recursive)

    if not files:
        logger.info("No supported files found in %s", path)
        return BatchReport()

    logger.info("Found %d supported files", len(files))

    report = BatchReport(total=len(files))
    batch_start = time.monotonic()

    if parallel <= 1:
        # Sequential — simpler, better error messages
        for i, f in enumerate(files, 1):
            logger.info("[%d/%d] %s", i, len(files), f.name)
            result = _ingest_one(f, settings, skip_enrichment, force)
            report.results.append(result)
            if result.error:
                report.failed += 1
            else:
                report.succeeded += 1
    else:
        # Cap per-worker LLM concurrency so total stays under the ceiling
        per_worker = max(1, settings.max_total_llm_concurrency // parallel)
        worker_settings = settings.model_copy(update={"llm_concurrency": per_worker})

        # Parallel via ProcessPoolExecutor
        with ProcessPoolExecutor(max_workers=parallel) as pool:
            futures = {
                pool.submit(_ingest_one, f, worker_settings, skip_enrichment, force): f
                for f in files
            }
            done_count = 0
            for future in as_completed(futures):
                done_count += 1
                f = futures[future]
                try:
                    result = future.result()
                except Exception as e:
                    result = FileResult(path=f, error=str(e))
                report.results.append(result)
                if result.error:
                    report.failed += 1
                    logger.info(
                        "[%d/%d] FAILED %s: %s", done_count, len(files), f.name, result.error
                    )
                else:
                    logger.info(
                        "[%d/%d] OK %s (%.1fs)",
                        done_count,
                        len(files),
                        f.name,
                        result.elapsed_seconds,
                    )

    report.elapsed_seconds = round(time.monotonic() - batch_start, 2)

    logger.info(
        "Batch complete: %d succeeded, %d failed, %.1fs total",
        report.succeeded,
        report.failed,
        report.elapsed_seconds,
    )

    return report
