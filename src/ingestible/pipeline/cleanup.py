"""Cleanup stale temporary files and checkpoints."""

from __future__ import annotations

import logging
import tempfile
import time
from pathlib import Path

from ingestible.config import Settings

logger = logging.getLogger(__name__)


def cleanup_stale(settings: Settings, max_age_hours: int = 24) -> dict[str, int]:
    """Remove stale checkpoints and temp files.

    Returns a dict with counts of cleaned items.
    """
    max_age_seconds = max_age_hours * 3600
    now = time.time()
    counts = {"checkpoints": 0, "temp_files": 0}

    # 1. Stale checkpoint directories in document dirs
    docs_dir = settings.documents_dir
    if docs_dir.exists():
        for doc_dir in docs_dir.iterdir():
            if not doc_dir.is_dir():
                continue
            cp_dir = doc_dir / ".checkpoint"
            if not cp_dir.exists():
                continue
            # Check age of the checkpoint directory
            try:
                mtime = cp_dir.stat().st_mtime
                if now - mtime > max_age_seconds:
                    import shutil

                    shutil.rmtree(cp_dir)
                    counts["checkpoints"] += 1
                    logger.info("Cleaned stale checkpoint: %s", cp_dir)
            except OSError:
                continue

    # 2. Stale lock files (leftover from crashed processes)
    if docs_dir.exists():
        for doc_dir in docs_dir.iterdir():
            if not doc_dir.is_dir():
                continue
            lock_file = doc_dir / ".lock"
            if lock_file.exists():
                try:
                    mtime = lock_file.stat().st_mtime
                    if now - mtime > max_age_seconds:
                        # Only delete if no process currently holds the lock
                        import portalocker

                        try:
                            lock = portalocker.Lock(
                                str(lock_file),
                                mode="w",
                                timeout=0,
                                flags=portalocker.LOCK_EX | portalocker.LOCK_NB,
                            )
                            lock.acquire()
                            lock.release()
                            # Lock was free — safe to delete
                            lock_file.unlink(missing_ok=True)
                            logger.info("Cleaned stale lock: %s", lock_file)
                        except portalocker.LockException:
                            # Lock is held by another process — skip
                            pass
                except OSError:
                    continue

    # 3. Temp files in system temp dir
    tmp_dir = Path(tempfile.gettempdir())
    for tmp_file in tmp_dir.glob("tmp*"):
        try:
            if not tmp_file.is_file():
                continue
            mtime = tmp_file.stat().st_mtime
            if now - mtime > max_age_seconds:
                # Only clean files that look like our temp uploads
                # (they have document-like extensions)
                ext = tmp_file.suffix.lower()
                if ext in (
                    ".pdf",
                    ".docx",
                    ".epub",
                    ".pptx",
                    ".xlsx",
                    ".csv",
                    ".html",
                    ".md",
                    ".txt",
                    ".wav",
                    ".mp3",
                    ".mp4",
                    ".mkv",
                ):
                    tmp_file.unlink(missing_ok=True)
                    counts["temp_files"] += 1
        except OSError:
            continue

    return counts
