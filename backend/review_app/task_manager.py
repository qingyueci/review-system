from __future__ import annotations

from threading import Lock
from typing import Any

from .job_store import JobStore


class TaskManager:
    """统一管理内存任务，并把分析任务同步写入 SQLite。"""

    def __init__(self, store: JobStore) -> None:
        self.store = store
        self.jobs: dict[str, dict[str, Any]] = {}
        self.lock = Lock()

    def register(
        self,
        job_id: str,
        job: dict[str, Any],
        request_payload: dict[str, Any] | None = None,
    ) -> str:
        with self.lock:
            fingerprint = job.get("request_fingerprint")
            if fingerprint:
                for existing_id, existing in self.jobs.items():
                    if (
                        existing.get("kind") == "analysis"
                        and existing.get("status") in {"pending", "running"}
                        and existing.get("request_fingerprint") == fingerprint
                    ):
                        return existing_id
            self.jobs[job_id] = dict(job)
            snapshot = dict(self.jobs[job_id])
        if job.get("kind") == "analysis":
            self.store.save(job_id, snapshot, request_payload)
            self.store.prune()
        return job_id

    def update(self, job_id: str, **updates: Any) -> dict[str, Any]:
        with self.lock:
            if job_id not in self.jobs:
                stored = self.store.get(job_id)
                if not stored:
                    raise KeyError(job_id)
                self.jobs[job_id] = stored
            self.jobs[job_id].update(updates)
            snapshot = dict(self.jobs[job_id])
        if snapshot.get("kind") == "analysis":
            self.store.save(job_id, snapshot)
        return snapshot

    def snapshot(self, job_id: str) -> dict[str, Any] | None:
        with self.lock:
            current = self.jobs.get(job_id)
            if current:
                return dict(current)
        stored = self.store.get(job_id)
        if stored:
            with self.lock:
                self.jobs[job_id] = dict(stored)
            return stored
        return None

    def find_running(self, kind: str) -> tuple[str, dict[str, Any]] | None:
        with self.lock:
            for job_id, job in self.jobs.items():
                if (
                    job.get("kind") == kind
                    and job.get("status") in {"pending", "running"}
                ):
                    return job_id, dict(job)
        return None
