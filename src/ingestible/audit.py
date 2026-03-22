"""Audit trail — logs data lifecycle events for compliance and debugging.

Events: search, ingest, delete, export, re_enrich, webhook.
All events include timestamp and user identity.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _write_event(audit_path: Path, event: dict[str, Any]) -> None:
    """Append an event to the audit log (JSONL)."""
    try:
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        with open(audit_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, default=str) + "\n")
    except Exception as e:
        logger.warning("Failed to write audit log: %s", e)


def log_search(
    audit_path: Path,
    *,
    query: str,
    doc_id: str | None,
    user: str = "",
    retrieved_chunk_ids: list[str],
    scores: list[float],
    n_results: int,
    latency_ms: float,
) -> None:
    """Log a search event."""
    _write_event(
        audit_path,
        {
            "timestamp": time.time(),
            "event": "search",
            "user": user,
            "doc_id": doc_id,
            "query": query,
            "retrieved_chunk_ids": retrieved_chunk_ids,
            "scores": [round(s, 4) for s in scores],
            "n_results": n_results,
            "latency_ms": round(latency_ms, 1),
        },
    )


def log_ingest(
    audit_path: Path,
    *,
    doc_id: str,
    user: str = "",
    title: str = "",
    source_path: str = "",
    total_chunks: int = 0,
    enriched: bool = False,
) -> None:
    """Log a document ingestion event."""
    _write_event(
        audit_path,
        {
            "timestamp": time.time(),
            "event": "ingest",
            "user": user,
            "doc_id": doc_id,
            "title": title,
            "source_path": source_path,
            "total_chunks": total_chunks,
            "enriched": enriched,
        },
    )


def log_delete(
    audit_path: Path,
    *,
    doc_id: str,
    user: str = "",
) -> None:
    """Log a document deletion event (proof of erasure for GDPR Art. 17)."""
    _write_event(
        audit_path,
        {
            "timestamp": time.time(),
            "event": "delete",
            "user": user,
            "doc_id": doc_id,
        },
    )


def log_export(
    audit_path: Path,
    *,
    doc_id: str,
    user: str = "",
    format: str = "",
) -> None:
    """Log a document export event."""
    _write_event(
        audit_path,
        {
            "timestamp": time.time(),
            "event": "export",
            "user": user,
            "doc_id": doc_id,
            "format": format,
        },
    )


def log_re_enrich(
    audit_path: Path,
    *,
    doc_id: str,
    user: str = "",
    changed_chunk_ids: list[str] | None = None,
) -> None:
    """Log a re-enrichment event."""
    _write_event(
        audit_path,
        {
            "timestamp": time.time(),
            "event": "re_enrich",
            "user": user,
            "doc_id": doc_id,
            "changed_chunk_ids": changed_chunk_ids,
        },
    )


def log_webhook(
    audit_path: Path,
    *,
    doc_id: str,
    chunk_id: str,
    event_type: str = "entry.updated",
) -> None:
    """Log an incoming webhook event."""
    _write_event(
        audit_path,
        {
            "timestamp": time.time(),
            "event": "webhook",
            "doc_id": doc_id,
            "chunk_id": chunk_id,
            "webhook_event": event_type,
        },
    )
