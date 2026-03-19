"""Tests for FileWatcher (P1).

Tests the file filter and debounce batch logic. Does NOT test actual
watchdog integration (flaky in CI, low risk).
"""

from __future__ import annotations

from pathlib import Path

from ingestible.config import Settings
from ingestible.pipeline.watcher import FileWatcher


def _make_watcher(tmp_path: Path) -> FileWatcher:
    settings = Settings(data_dir=tmp_path / "data")
    return FileWatcher(
        watch_dir=tmp_path,
        settings=settings,
    )


class TestFileFilter:
    def test_supported_extensions_accepted(self, tmp_path):
        watcher = _make_watcher(tmp_path)
        for ext in [".pdf", ".md", ".txt", ".docx", ".html", ".htm", ".epub",
                    ".csv", ".xlsx", ".pptx", ".rst", ".adoc"]:
            p = tmp_path / f"test{ext}"
            assert watcher._is_supported(p), f"{ext} should be supported"

    def test_unsupported_extensions_rejected(self, tmp_path):
        watcher = _make_watcher(tmp_path)
        for ext in [".jpg", ".png", ".mp3", ".zip", ".py", ".js", ".json"]:
            p = tmp_path / f"test{ext}"
            assert not watcher._is_supported(p), f"{ext} should NOT be supported"

    def test_dotfiles_rejected(self, tmp_path):
        watcher = _make_watcher(tmp_path)
        assert not watcher._is_supported(tmp_path / ".hidden.md")
        assert not watcher._is_supported(tmp_path / ".DS_Store")

    def test_case_insensitive(self, tmp_path):
        watcher = _make_watcher(tmp_path)
        assert watcher._is_supported(tmp_path / "FILE.PDF")
        assert watcher._is_supported(tmp_path / "readme.MD")
        assert watcher._is_supported(tmp_path / "data.XLSX")


class TestPendingBatch:
    def test_pending_dedup(self, tmp_path):
        """Same file changed multiple times should appear once in pending."""
        watcher = _make_watcher(tmp_path)

        # Simulate adding the same path multiple times
        path = tmp_path / "test.md"
        with watcher._lock:
            watcher._pending.add(path)
            watcher._pending.add(path)
            watcher._pending.add(path)

        assert len(watcher._pending) == 1

    def test_multiple_files_batched(self, tmp_path):
        """Multiple different files should all be in the pending set."""
        watcher = _make_watcher(tmp_path)

        paths = [tmp_path / f"file{i}.md" for i in range(5)]
        with watcher._lock:
            for p in paths:
                watcher._pending.add(p)

        assert len(watcher._pending) == 5
