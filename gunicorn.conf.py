"""Gunicorn configuration for production deployment."""

import multiprocessing
import os

# Server socket
bind = "0.0.0.0:8081"

# Worker processes — override with WEB_CONCURRENCY env var
workers = int(os.environ.get("WEB_CONCURRENCY", min(multiprocessing.cpu_count() * 2 + 1, 8)))
worker_class = "uvicorn.workers.UvicornWorker"

# Timeouts
timeout = 600  # 10 min — ingestion can be slow
graceful_timeout = 30
keepalive = 5

# Preload shares model memory across workers but needs enough RAM for the initial load.
# Disable with GUNICORN_PRELOAD=false for memory-constrained environments.
preload_app = os.environ.get("GUNICORN_PRELOAD", "true").lower() != "false"

# Logging (handled by structlog, so keep gunicorn minimal)
accesslog = "-"
errorlog = "-"
loglevel = "warning"

# Limits
max_requests = 1000  # restart workers after N requests (leak protection)
max_requests_jitter = 100  # randomise to avoid thundering herd
