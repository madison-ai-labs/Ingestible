"""Tests for WP 5.2 — Streaming Progress Callbacks."""

from __future__ import annotations

from ingestible.pipeline.progress import CLIProgress, LogProgress, SSEProgress


def test_log_progress_runs(caplog):
    import logging
    caplog.set_level(logging.INFO)
    cb = LogProgress()
    cb(1, 5, "Parsing...")
    assert "1/5" in caplog.text
    assert "Parsing..." in caplog.text


def test_cli_progress_writes_to_stderr(capsys):
    cb = CLIProgress()
    cb(1, 4, "Step one")
    cb(4, 4, "Done")
    captured = capsys.readouterr()
    assert "Step one" in captured.err
    assert "Done" in captured.err


def test_sse_progress_collects_events():
    cb = SSEProgress()
    cb(1, 3, "Parsing...")
    cb(2, 3, "Chunking...")
    cb(3, 3, "Done")

    assert len(cb.events) == 3
    assert cb.events[0]["step"] == 1
    assert cb.events[0]["total"] == 3
    assert cb.events[0]["message"] == "Parsing..."
    assert cb.events[2]["progress"] == 1.0


def test_sse_progress_zero_total():
    cb = SSEProgress()
    cb(0, 0, "Empty")
    assert cb.events[0]["progress"] == 0


def test_cli_progress_percent(capsys):
    cb = CLIProgress()
    cb(2, 4, "Half")
    captured = capsys.readouterr()
    assert "50%" in captured.err
