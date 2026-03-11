"""Tests for Feature 3 — Incremental/Delta Processing."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest


@pytest.fixture(autouse=True)
def _mock_chromadb(monkeypatch):
    """Prevent chromadb import failure on Python 3.14."""
    if "chromadb" not in sys.modules:
        monkeypatch.setitem(sys.modules, "chromadb", MagicMock())
        monkeypatch.setitem(sys.modules, "chromadb.api", MagicMock())
        monkeypatch.setitem(sys.modules, "chromadb.api.client", MagicMock())
        monkeypatch.setitem(sys.modules, "chromadb.config", MagicMock())


from ingestible.config import Settings


def _import_orchestrator():
    from ingestible.pipeline.orchestrator import (
        _check_existing,
        _compute_content_hash,
        generate_doc_id,
    )
    return _compute_content_hash, _check_existing, generate_doc_id


def test_content_hash_deterministic(tmp_path):
    _compute_content_hash, _, _ = _import_orchestrator()
    f = tmp_path / "test.txt"
    f.write_text("hello world")
    h1 = _compute_content_hash(f)
    h2 = _compute_content_hash(f)
    assert h1 == h2
    assert len(h1) == 64  # SHA-256 hex


def test_content_hash_changes_on_different_content(tmp_path):
    _compute_content_hash, _, _ = _import_orchestrator()
    f1 = tmp_path / "a.txt"
    f2 = tmp_path / "b.txt"
    f1.write_text("content A")
    f2.write_text("content B")
    assert _compute_content_hash(f1) != _compute_content_hash(f2)


def test_check_existing_matches(tmp_path):
    _, _check_existing, _ = _import_orchestrator()
    settings = Settings(data_dir=tmp_path)
    doc_dir = settings.documents_dir / "test-doc"
    doc_dir.mkdir(parents=True)
    meta = {"doc_id": "test-doc", "content_hash": "abc123"}
    (doc_dir / "meta.json").write_text(json.dumps(meta))

    result = _check_existing("test-doc", "abc123", settings)
    assert result == doc_dir


def test_check_existing_no_match(tmp_path):
    _, _check_existing, _ = _import_orchestrator()
    settings = Settings(data_dir=tmp_path)
    doc_dir = settings.documents_dir / "test-doc"
    doc_dir.mkdir(parents=True)
    meta = {"doc_id": "test-doc", "content_hash": "abc123"}
    (doc_dir / "meta.json").write_text(json.dumps(meta))

    result = _check_existing("test-doc", "different_hash", settings)
    assert result is None


def test_check_existing_missing_meta(tmp_path):
    _, _check_existing, _ = _import_orchestrator()
    settings = Settings(data_dir=tmp_path)
    result = _check_existing("nonexistent", "abc", settings)
    assert result is None


def test_check_existing_old_format_meta(tmp_path):
    _, _check_existing, _ = _import_orchestrator()
    settings = Settings(data_dir=tmp_path)
    doc_dir = settings.documents_dir / "test-doc"
    doc_dir.mkdir(parents=True)
    meta = {"doc_id": "test-doc", "title": "Old Doc"}
    (doc_dir / "meta.json").write_text(json.dumps(meta))

    result = _check_existing("test-doc", "abc123", settings)
    assert result is None


def test_force_bypass(tmp_path):
    _, _check_existing, _ = _import_orchestrator()
    settings = Settings(data_dir=tmp_path)
    doc_dir = settings.documents_dir / "test-doc"
    doc_dir.mkdir(parents=True)
    meta = {"doc_id": "test-doc", "content_hash": "abc123"}
    (doc_dir / "meta.json").write_text(json.dumps(meta))

    # Function still returns match — it's the caller that decides based on force
    result = _check_existing("test-doc", "abc123", settings)
    assert result is not None
