"""Tests for Feature 5 — Document Deduplication."""

from __future__ import annotations

import json
import sys
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


def _import_dedup():
    from ingestible.pipeline.orchestrator import _check_duplicate_content
    return _check_duplicate_content


def test_dedup_same_content_different_path(tmp_path):
    _check_duplicate_content = _import_dedup()
    settings = Settings(data_dir=tmp_path)
    doc_dir = settings.documents_dir / "existing-doc"
    doc_dir.mkdir(parents=True)
    meta = {"doc_id": "existing-doc", "content_hash": "abc123"}
    (doc_dir / "meta.json").write_text(json.dumps(meta))

    result = _check_duplicate_content("abc123", "new-doc", settings)
    assert result == doc_dir


def test_dedup_different_content(tmp_path):
    _check_duplicate_content = _import_dedup()
    settings = Settings(data_dir=tmp_path)
    doc_dir = settings.documents_dir / "existing-doc"
    doc_dir.mkdir(parents=True)
    meta = {"doc_id": "existing-doc", "content_hash": "abc123"}
    (doc_dir / "meta.json").write_text(json.dumps(meta))

    result = _check_duplicate_content("different_hash", "new-doc", settings)
    assert result is None


def test_dedup_skips_self(tmp_path):
    _check_duplicate_content = _import_dedup()
    settings = Settings(data_dir=tmp_path)
    doc_dir = settings.documents_dir / "my-doc"
    doc_dir.mkdir(parents=True)
    meta = {"doc_id": "my-doc", "content_hash": "abc123"}
    (doc_dir / "meta.json").write_text(json.dumps(meta))

    result = _check_duplicate_content("abc123", "my-doc", settings)
    assert result is None


def test_dedup_empty_documents_dir(tmp_path):
    _check_duplicate_content = _import_dedup()
    settings = Settings(data_dir=tmp_path)
    result = _check_duplicate_content("abc123", "new-doc", settings)
    assert result is None


def test_dedup_disabled_via_config(tmp_path):
    settings = Settings(data_dir=tmp_path, dedup_enabled=False)
    assert settings.dedup_enabled is False
