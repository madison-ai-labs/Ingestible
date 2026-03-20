"""Gunicorn configuration for production deployment."""

import multiprocessing

# Server socket
bind = "0.0.0.0:8081"

# Worker processes
workers = min(multiprocessing.cpu_count() * 2 + 1, 8)  # cap at 8
worker_class = "uvicorn.workers.UvicornWorker"

# Timeouts
timeout = 600  # 10 min — ingestion can be slow
graceful_timeout = 30
keepalive = 5

# Preload for faster worker startup (shares model memory)
preload_app = True

# Logging (handled by structlog, so keep gunicorn minimal)
accesslog = "-"
errorlog = "-"
loglevel = "warning"

# Limits
max_requests = 1000  # restart workers after N requests (leak protection)
max_requests_jitter = 100  # randomise to avoid thundering herd
