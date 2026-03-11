"""URL fetching — download a URL to a temp file for ingestion."""

from __future__ import annotations

import logging
import mimetypes
import re
import tempfile
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Map content-types to file extensions
CONTENT_TYPE_MAP = {
    "application/pdf": ".pdf",
    "text/html": ".html",
    "text/plain": ".txt",
    "text/markdown": ".md",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
}


def is_url(path: str) -> bool:
    """Check if a string looks like an HTTP(S) URL."""
    return path.startswith("http://") or path.startswith("https://")


def fetch_url(url: str, use_readability: bool = True) -> Path:
    """Download a URL to a temporary file. Returns the path.

    For HTML content, optionally uses readability-lxml to extract the
    article body before saving.

    The caller is responsible for cleaning up the temp file.
    """
    import httpx

    logger.info("Fetching URL: %s", url)

    with httpx.Client(follow_redirects=True, timeout=60) as client:
        resp = client.get(url)
        resp.raise_for_status()

    content_type = resp.headers.get("content-type", "")
    ext = _detect_extension(url, content_type)

    if ext in (".html", ".htm") and use_readability:
        content = _extract_readable(resp.text, url)
        suffix = ".html"
        with tempfile.NamedTemporaryFile(
            delete=False, suffix=suffix, mode="w", encoding="utf-8"
        ) as tmp:
            tmp.write(content)
            return Path(tmp.name)
    else:
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
            tmp.write(resp.content)
            return Path(tmp.name)


def _detect_extension(url: str, content_type: str) -> str:
    """Determine file extension from content-type header and URL."""
    # Try content-type first (strip params like charset)
    ct_base = content_type.split(";")[0].strip().lower()
    if ct_base in CONTENT_TYPE_MAP:
        return CONTENT_TYPE_MAP[ct_base]

    # Try URL path extension
    parsed = urlparse(url)
    path_ext = Path(parsed.path).suffix.lower()
    if path_ext in {".pdf", ".md", ".txt", ".docx", ".html", ".htm"}:
        return path_ext

    # Fallback: guess from content-type via mimetypes
    ext = mimetypes.guess_extension(ct_base)
    if ext:
        return ext

    # Default to HTML for web pages
    if ct_base.startswith("text/"):
        return ".html"

    return ".html"


def _extract_readable(html: str, url: str) -> str:
    """Try to extract article content using readability-lxml. Falls back to raw HTML."""
    try:
        from readability import Document

        doc = Document(html, url=url)
        title = doc.title()
        content = doc.summary()
        # Wrap with title for better parsing downstream
        return f"<html><head><title>{title}</title></head><body><h1>{title}</h1>{content}</body></html>"
    except ImportError:
        logger.debug("readability-lxml not installed, using raw HTML")
        return html
    except Exception as e:
        logger.warning("Readability extraction failed, using raw HTML: %s", e)
        return html
