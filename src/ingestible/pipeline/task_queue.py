"""Lightweight in-process task queue for background ingestion jobs."""

from __future__ import annotations

import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from ingestible.config import Settings

logger = logging.getLogger(__name__)


class JobStatus(str, Enum):
    pending = "pending"
    running = "running"
    complete = "complete"
    failed = "failed"


@dataclass
class Job:
    job_id: str
    status: JobStatus = JobStatus.pending
    doc_id: str | None = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    progress_stage: str = ""
    progress_step: int = 0
    progress_total: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "status": self.status.value,
            "doc_id": self.doc_id,
            "error": self.error,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "progress_stage": self.progress_stage,
            "progress_step": self.progress_step,
            "progress_total": self.progress_total,
        }


class UserConcurrencyExceeded(Exception):
    """Raised when a user exceeds their per-user concurrent ingestion limit."""


class TaskQueue:
    """In-process task queue backed by a ThreadPoolExecutor."""

    def __init__(self, max_workers: int = 2, max_jobs_per_user: int = 1):
        self._pool = ThreadPoolExecutor(max_workers=max_workers)
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._user_jobs: dict[str, int] = {}
        self._user_lock = threading.Lock()
        self._max_jobs_per_user = max_jobs_per_user

    def submit_ingestion(
        self,
        file_path: str | Path,
        settings: Settings,
        *,
        skip_enrichment: bool = False,
        force: bool = False,
        user: str = "anonymous",
    ) -> Job:
        with self._user_lock:
            if self._user_jobs.get(user, 0) >= self._max_jobs_per_user:
                raise UserConcurrencyExceeded(
                    "Too many concurrent ingestions. Please wait for current jobs to finish."
                )
            self._user_jobs[user] = self._user_jobs.get(user, 0) + 1

        job = Job(job_id=uuid.uuid4().hex[:16])
        with self._lock:
            self._jobs[job.job_id] = job

        self._pool.submit(
            self._run_ingestion, job, file_path, settings, skip_enrichment, force, user
        )
        return job

    def get_job(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list_jobs(self) -> list[Job]:
        with self._lock:
            return list(self._jobs.values())

    def _run_ingestion(
        self,
        job: Job,
        file_path: str | Path,
        settings: Settings,
        skip_enrichment: bool,
        force: bool,
        user: str = "anonymous",
    ) -> None:
        from ingestible.pipeline.orchestrator import ingest
        from ingestible.pipeline.stage6_storage import load_document_meta

        job.status = JobStatus.running
        job.started_at = time.time()

        def _progress(step: int, total: int, msg: str) -> None:
            job.progress_step = step
            job.progress_total = total
            job.progress_stage = msg

        try:
            doc_dir = ingest(
                file_path,
                settings,
                skip_enrichment=skip_enrichment,
                force=force,
                verbose=False,
                progress_callback=_progress,
            )
            meta = load_document_meta(doc_dir)
            job.doc_id = meta.get("doc_id", doc_dir.name)
            job.status = JobStatus.complete
        except Exception as e:
            logger.error("Ingestion job %s failed: %s", job.job_id, e)
            job.status = JobStatus.failed
            job.error = str(e)
        finally:
            job.finished_at = time.time()
            with self._user_lock:
                self._user_jobs[user] = max(0, self._user_jobs.get(user, 0) - 1)

    def shutdown(self, wait: bool = True, timeout: float = 30.0) -> None:
        """Shut down the pool, optionally waiting for in-progress jobs."""
        self._pool.shutdown(wait=wait)

    def active_count(self) -> int:
        with self._lock:
            return sum(1 for j in self._jobs.values() if j.status == JobStatus.running)


# Module-level singleton — lazy-initialised
_queue: TaskQueue | None = None
_queue_lock = threading.Lock()


def get_task_queue(max_workers: int = 2, max_jobs_per_user: int = 1) -> TaskQueue:
    global _queue
    if _queue is None:
        with _queue_lock:
            if _queue is None:
                _queue = TaskQueue(
                    max_workers=max_workers, max_jobs_per_user=max_jobs_per_user
                )
    return _queue
