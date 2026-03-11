"""Progress callbacks — WP 5.2.

Protocol and implementations for streaming pipeline progress.
"""

from __future__ import annotations

import logging
import sys
from typing import Protocol

logger = logging.getLogger(__name__)


class ProgressCallback(Protocol):
    """Protocol for pipeline progress reporting."""

    def __call__(self, step: int, total: int, message: str) -> None: ...


class LogProgress:
    """Default progress: log to Python logger."""

    def __call__(self, step: int, total: int, message: str) -> None:
        logger.info("[%d/%d] %s", step, total, message)


class CLIProgress:
    """Terminal progress bar for CLI usage."""

    def __init__(self) -> None:
        self._last_msg = ""

    def __call__(self, step: int, total: int, message: str) -> None:
        bar_width = 30
        filled = int(bar_width * step / total) if total > 0 else 0
        bar = "=" * filled + ">" + " " * (bar_width - filled - 1)
        pct = int(100 * step / total) if total > 0 else 0
        line = f"\r  [{bar}] {pct:3d}%  {message}"
        sys.stderr.write(line)
        sys.stderr.flush()
        if step >= total:
            sys.stderr.write("\n")
            sys.stderr.flush()


class SSEProgress:
    """Server-Sent Events progress for API streaming."""

    def __init__(self) -> None:
        self.events: list[dict] = []

    def __call__(self, step: int, total: int, message: str) -> None:
        self.events.append({
            "step": step,
            "total": total,
            "message": message,
            "progress": round(step / total, 2) if total > 0 else 0,
        })
