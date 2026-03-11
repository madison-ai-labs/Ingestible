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


def test_fetch_url_mock(tmp_path):
    """fetch_url downloads content to a temp file."""
    mock_response = MagicMock()
    mock_response.headers = {"content-type": "application/pdf"}
    mock_response.content = b"%PDF-1.4 fake pdf content"
    mock_response.raise_for_status = MagicMock()

    mock_client_instance = MagicMock()
    mock_client_instance.get.return_value = mock_response
    mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
    mock_client_instance.__exit__ = MagicMock(return_value=False)

    with patch("httpx.Client", return_value=mock_client_instance):
        from ingestible.pipeline.fetch import fetch_url

        result = fetch_url("https://example.com/doc.pdf", use_readability=False)

    assert result.exists()
    assert result.suffix == ".pdf"
    content = result.read_bytes()
    assert b"PDF" in content
    result.unlink()


def test_fetch_url_html_with_readability_mock():
    """fetch_url processes HTML through readability when available."""
    mock_response = MagicMock()
    mock_response.headers = {"content-type": "text/html"}
    mock_response.text = "<html><body><article><p>Article content</p></article></body></html>"
    mock_response.content = mock_response.text.encode()
    mock_response.raise_for_status = MagicMock()

    mock_client_instance = MagicMock()
    mock_client_instance.get.return_value = mock_response
    mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
    mock_client_instance.__exit__ = MagicMock(return_value=False)

    with patch("httpx.Client", return_value=mock_client_instance):
        from ingestible.pipeline.fetch import fetch_url

        result = fetch_url("https://example.com/article", use_readability=True)

    assert result.exists()
    assert result.suffix == ".html"
    content = result.read_text()
    assert "Article content" in content or "article" in content.lower()
    result.unlink()
