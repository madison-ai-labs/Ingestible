"""File watcher — auto-ingest on file changes.

Uses ``watchdog`` for OS-native filesystem events with directory-level
debouncing to batch rapid writes (e.g. git checkout, editor batch-saves).
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from ingestible.config import Settings
from ingestible.pipeline.stage1_parsing import SUPPORTED_FORMATS

if TYPE_CHECKING:
    from ingestible.adapters.cv_export import CVConfig

logger = logging.getLogger(__name__)

# Debounce window in seconds — collects all changes within this window
# and processes them as a single batch.
DEBOUNCE_SECONDS = 2.0


class FileWatcher:
    """Watch a directory for file changes and auto-ingest.

    Args:
        watch_dir: Directory to watch for changes.
        settings: Ingestible settings.
        skip_enrichment: Skip LLM enrichment.
        cv_push: Auto-push to CognitiveVault after batch completes.
        cv_config: CVConfig for push (required if cv_push=True).
    """

    def __init__(
        self,
        watch_dir: Path,
        settings: Settings,
        skip_enrichment: bool = False,
        cv_push: bool = False,
        cv_config: "CVConfig | None" = None,
    ):
        self.watch_dir = watch_dir.resolve()
        self.settings = settings
        self.skip_enrichment = skip_enrichment
        self.cv_push = cv_push
        self.cv_config = cv_config

        self._pending: set[Path] = set()
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None
        self._observer = None

    def _is_supported(self, path: Path) -> bool:
        return path.suffix.lower() in SUPPORTED_FORMATS and not path.name.startswith(".")

    def _on_event(self, event) -> None:
        """Called by watchdog on any filesystem event."""
        if event.is_directory:
            return

        path = Path(event.src_path)
        if not self._is_supported(path):
            return

        with self._lock:
            self._pending.add(path)
            # Reset debounce timer
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(DEBOUNCE_SECONDS, self._process_batch)
            self._timer.start()

    def _process_batch(self) -> None:
        """Process all pending file changes as a batch."""
        with self._lock:
            files = list(self._pending)
            self._pending.clear()
            self._timer = None

        if not files:
            return

        # Dedup and filter to files that still exist
        files = sorted({f for f in files if f.exists()})
        if not files:
            return

        logger.info("Watch: processing %d changed file(s)", len(files))

        from ingestible.pipeline.orchestrator import ingest

        doc_dirs = []
        for file_path in files:
            try:
                logger.info("  Ingesting %s", file_path.name)
                doc_dir = ingest(
                    file_path,
                    self.settings,
                    skip_enrichment=self.skip_enrichment,
                    force=True,
                )
                doc_dirs.append(doc_dir)
            except Exception as e:
                logger.error("  Failed to ingest %s: %s", file_path.name, e)

        # CV push after entire batch
        if self.cv_push and self.cv_config and doc_dirs:
            self._push_to_cv(doc_dirs)

    def _push_to_cv(self, doc_dirs: list[Path]) -> None:
        """Push ingested documents to CognitiveVault."""
        from ingestible.adapters.cv_export import export_to_cv
        from ingestible.pipeline.stage6_storage import load_chunks

        for doc_dir in doc_dirs:
            try:
                chunks = load_chunks(doc_dir)
                result = export_to_cv(chunks, self.cv_config)
                logger.info(
                    "  CV push %s: created=%d updated=%d unchanged=%d",
                    chunks.doc_id,
                    result.created,
                    result.updated,
                    result.unchanged,
                )
            except Exception as e:
                logger.error("  CV push failed for %s: %s", doc_dir.name, e)

    def start(self) -> None:
        """Start watching. Blocks until interrupted."""
        try:
            from watchdog.events import FileSystemEventHandler
            from watchdog.observers import Observer
        except ImportError:
            raise ImportError(
                "watchdog is required for file watching. "
                "Install it with: pip install ingestible[watch]"
            )

        class _Handler(FileSystemEventHandler):
            def __init__(self, watcher: FileWatcher):
                self._watcher = watcher

            def on_created(self, event):
                self._watcher._on_event(event)

            def on_modified(self, event):
                self._watcher._on_event(event)

        handler = _Handler(self)
        self._observer = Observer()
        self._observer.schedule(handler, str(self.watch_dir), recursive=True)
        self._observer.start()

        logger.info("Watching %s for changes (Ctrl+C to stop)", self.watch_dir)
        print(f"Watching {self.watch_dir} for changes (Ctrl+C to stop)")

        try:
            while self._observer.is_alive():
                self._observer.join(timeout=1)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()

    def stop(self) -> None:
        """Stop watching."""
        if self._timer is not None:
            self._timer.cancel()
        # Process any remaining pending files
        self._process_batch()
        if self._observer is not None:
            self._observer.stop()
            self._observer.join()
        logger.info("Watcher stopped")
