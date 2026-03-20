"""Tests for WP 1.4 — URL ingestion (fetch module)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from ingestible.pipeline.fetch import _detect_extension, _extract_readable, is_url


def test_is_url_http():
    assert is_url("http://example.com/doc.pdf")


def test_is_url_https():
    assert is_url("https://example.com/doc.pdf")


def test_is_url_local_path():
    assert not is_url("/tmp/doc.pdf")


def test_is_url_relative_path():
    assert not is_url("docs/file.txt")


def test_detect_extension_from_content_type():
    assert _detect_extension("https://example.com/doc", "application/pdf") == ".pdf"
    assert _detect_extension("https://example.com/doc", "text/html; charset=utf-8") == ".html"
    assert _detect_extension("https://example.com/doc", "text/plain") == ".txt"


def test_detect_extension_from_url():
    assert _detect_extension("https://example.com/report.pdf", "application/octet-stream") == ".pdf"
    assert _detect_extension("https://example.com/readme.md", "application/octet-stream") == ".md"


def test_detect_extension_fallback():
    """Unknown content-type for web page defaults to .html."""
    ext = _detect_extension("https://example.com/page", "text/whatever")
    assert ext == ".html"


def test_extract_readable_fallback():
    """Falls back to raw HTML when readability import fails."""
    html = "<html><body><p>Hello</p></body></html>"
    # Simulate readability not installed by removing it from sys.modules
    import sys

    with patch.dict(sys.modules, {"readability": None}):
        result = _extract_readable(html, "https://example.com")
    # Should fall back to returning raw HTML
    assert "Hello" in result


def _make_streaming_client(body: bytes, headers: dict):
    """Build a mock httpx.Client that supports the streaming API."""
    mock_response = MagicMock()
    mock_response.headers = headers
    mock_response.raise_for_status = MagicMock()
    mock_response.iter_bytes = MagicMock(return_value=iter([body]))
    # Context-manager support for the response (client.stream)
    mock_response.__enter__ = MagicMock(return_value=mock_response)
    mock_response.__exit__ = MagicMock(return_value=False)

    mock_client = MagicMock()
    mock_client.stream = MagicMock(return_value=mock_response)
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    return mock_client


def test_fetch_url_mock(tmp_path):
    """fetch_url downloads content to a temp file."""
    body = b"%PDF-1.4 fake pdf content"
    mock_client = _make_streaming_client(body, {"content-type": "application/pdf"})

    with patch("httpx.Client", return_value=mock_client):
        from ingestible.pipeline.fetch import fetch_url

        result = fetch_url("https://example.com/doc.pdf", use_readability=False)

    assert result.exists()
    assert result.suffix == ".pdf"
    content = result.read_bytes()
    assert b"PDF" in content
    result.unlink()


def test_fetch_url_html_with_readability_mock():
    """fetch_url processes HTML through readability when available."""
    html = "<html><body><article><p>Article content</p></article></body></html>"
    mock_client = _make_streaming_client(html.encode(), {"content-type": "text/html"})

    with patch("httpx.Client", return_value=mock_client):
        from ingestible.pipeline.fetch import fetch_url

        result = fetch_url("https://example.com/article", use_readability=True)

    assert result.exists()
    assert result.suffix == ".html"
    content = result.read_text()
    assert "Article content" in content or "article" in content.lower()
    result.unlink()


def test_fetch_url_rejects_large_content_length():
    """fetch_url raises FileTooLargeError when Content-Length exceeds max_bytes."""
    mock_client = _make_streaming_client(
        b"x", {"content-type": "application/pdf", "content-length": "1000000"}
    )

    with patch("httpx.Client", return_value=mock_client):
        import pytest

        from ingestible.pipeline.fetch import FileTooLargeError, fetch_url

        with pytest.raises(FileTooLargeError):
            fetch_url("https://example.com/big.pdf", max_bytes=100)


def test_fetch_url_rejects_large_stream():
    """fetch_url raises FileTooLargeError when streamed body exceeds max_bytes."""
    body = b"x" * 2000
    mock_client = _make_streaming_client(body, {"content-type": "application/pdf"})

    with patch("httpx.Client", return_value=mock_client):
        import pytest

        from ingestible.pipeline.fetch import FileTooLargeError, fetch_url

        with pytest.raises(FileTooLargeError):
            fetch_url("https://example.com/big.pdf", max_bytes=100)
