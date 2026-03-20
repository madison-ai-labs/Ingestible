"""Tests for WP 4.2 — Language detection + multilingual BM25."""

from __future__ import annotations

import pickle
from pathlib import Path

from ingestible.search.bm25_store import BM25Store
from ingestible.utils.language import _simple_tokenize, detect_language, get_tokenizer

# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------


def test_detect_english():
    lang = detect_language("Machine learning is a branch of artificial intelligence.")
    assert lang == "en"


def test_detect_short_text_defaults_to_en():
    """Very short text defaults to English."""
    lang = detect_language("Hi")
    assert lang == "en"


def test_detect_empty_defaults_to_en():
    assert detect_language("") == "en"


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------


def test_simple_tokenize():
    tokens = _simple_tokenize("Hello, World! This is a test.")
    assert "hello" in tokens
    assert "world" in tokens
    assert "," not in tokens


def test_get_tokenizer_english():
    """English tokenizer returns a callable."""
    tokenize = get_tokenizer("en")
    tokens = tokenize("running quickly through forests")
    assert len(tokens) > 0
    assert all(isinstance(t, str) for t in tokens)


def test_get_tokenizer_unknown_lang():
    """Unknown language falls back to simple tokenizer."""
    tokenize = get_tokenizer("xx")
    tokens = tokenize("hello world")
    assert "hello" in tokens
    assert "world" in tokens


# ---------------------------------------------------------------------------
# Language-aware BM25
# ---------------------------------------------------------------------------


def test_bm25_with_language():
    store = BM25Store(language="en")
    store.add_documents(
        ["c1", "c2", "c3", "c4"],
        [
            "machine learning algorithms and models",
            "cooking recipes and food preparation",
            "data science and statistical analysis",
            "gardening tips for spring flowers",
        ],
    )
    store.build()
    results = store.query("machine learning")
    assert len(results) > 0
    assert results[0][0] == "c1"


def test_bm25_save_load_preserves_language(tmp_path: Path):
    """Language is preserved through save/load."""
    store = BM25Store(language="fr")
    store.add_documents(["c1"], ["apprentissage automatique"])
    store.build()

    path = tmp_path / "bm25.pkl"
    store.save(path)

    loaded = BM25Store.load(path)
    assert loaded._language == "fr"


def test_bm25_default_language():
    """Default language is English."""
    store = BM25Store()
    assert store._language == "en"


def test_bm25_backward_compat_load(tmp_path: Path):
    """Loading old pickles without language field defaults to 'en'."""
    # Simulate old format
    path = tmp_path / "old_bm25.pkl"
    with open(path, "wb") as f:
        pickle.dump(
            {"chunk_ids": ["c1"], "corpus_tokens": [["hello", "world"]]},
            f,
        )

    loaded = BM25Store.load(path)
    assert loaded._language == "en"
    assert loaded.count == 1
