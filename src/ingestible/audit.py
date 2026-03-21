"""Retrieval audit trail — logs every search for compliance and debugging."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)


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
    """Append a search event to the audit log (JSONL)."""
    event = {
        "timestamp": time.time(),
        "event": "search",
        "query": query,
        "doc_id": doc_id,
        "user": user,
        "retrieved_chunk_ids": retrieved_chunk_ids,
        "scores": [round(s, 4) for s in scores],
        "n_results": n_results,
        "latency_ms": round(latency_ms, 1),
    }
    try:
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        with open(audit_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, default=str) + "\n")
    except Exception as e:
        logger.warning("Failed to write audit log: %s", e)
