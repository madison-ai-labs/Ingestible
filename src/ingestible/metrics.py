"""Prometheus metrics for the Ingestible pipeline."""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

# Ingestion metrics
INGEST_DURATION = Histogram(
    "ingestible_ingest_duration_seconds",
    "Duration of document ingestion by stage",
    ["stage"],
    buckets=[1, 5, 10, 30, 60, 120, 300, 600],
)

INGEST_TOTAL = Counter(
    "ingestible_ingest_total",
    "Total ingestion attempts",
    ["status"],  # success, failed, skipped
)

ACTIVE_INGESTIONS = Gauge(
    "ingestible_active_ingestions",
    "Number of currently running ingestion jobs",
)

# LLM metrics
LLM_CALLS_TOTAL = Counter(
    "ingestible_llm_calls_total",
    "Total LLM API calls",
    ["provider", "status"],  # status: success, error, retry
)

LLM_CALL_DURATION = Histogram(
    "ingestible_llm_call_duration_seconds",
    "Duration of individual LLM API calls",
    ["provider"],
    buckets=[0.5, 1, 2, 5, 10, 30, 60],
)

# Document metrics
DOCUMENTS_TOTAL = Gauge(
    "ingestible_documents_total",
    "Total number of stored documents",
)

# Search metrics
SEARCH_DURATION = Histogram(
    "ingestible_search_duration_seconds",
    "Duration of search queries",
    ["scope"],  # single_doc, corpus
    buckets=[0.05, 0.1, 0.25, 0.5, 1, 2, 5],
)

SEARCH_TOTAL = Counter(
    "ingestible_search_total",
    "Total search queries",
    ["scope"],
)
