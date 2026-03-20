"""Document-level file locking to prevent concurrent write corruption."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path

import portalocker

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 120  # seconds


@contextmanager
def document_lock(doc_dir: Path, timeout: float = _DEFAULT_TIMEOUT):
    """Acquire an exclusive file lock on a document directory.

    Uses a .lock file inside the document directory. Blocks until the lock
    is acquired or the timeout is reached.
    """
    doc_dir.mkdir(parents=True, exist_ok=True)
    lock_path = doc_dir / ".lock"

    lock = portalocker.Lock(
        str(lock_path),
        mode="w",
        timeout=timeout,
        flags=portalocker.LOCK_EX,
    )
    try:
        lock.acquire()
        logger.debug("Acquired lock on %s", doc_dir.name)
        yield
    except portalocker.LockException:
        raise TimeoutError(
            f"Could not acquire lock on {doc_dir.name} within {timeout}s — "
            f"another ingestion or re-enrichment may be in progress"
        )
    finally:
        try:
            lock.release()
            logger.debug("Released lock on %s", doc_dir.name)
        except Exception:
            pass
