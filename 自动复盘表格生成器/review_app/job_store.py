from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import sqlite3
from typing import Any

from .config import JOB_DB_PATH


class JobStore:
    """持久化生成任务，服务重启后仍可查询结果和失败原因。"""

    def __init__(self, path: Path = JOB_DB_PATH) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS generation_jobs (
                    job_id TEXT PRIMARY KEY,
                    job_json TEXT NOT NULL,
                    request_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_generation_jobs_updated
                ON generation_jobs(updated_at DESC)
                """
            )

    def save(
        self,
        job_id: str,
        job: dict[str, Any],
        request_payload: dict[str, Any] | None = None,
    ) -> None:
        now = datetime.now().isoformat(timespec="microseconds")
        job_json = json.dumps(job, ensure_ascii=False)
        request_json = (
            json.dumps(request_payload, ensure_ascii=False)
            if request_payload is not None
            else None
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO generation_jobs (
                    job_id, job_json, request_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    job_json = excluded.job_json,
                    request_json = COALESCE(
                        excluded.request_json,
                        generation_jobs.request_json
                    ),
                    updated_at = excluded.updated_at
                """,
                (job_id, job_json, request_json, now, now),
            )

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT job_json FROM generation_jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
        return json.loads(row["job_json"]) if row else None

    def get_request(self, job_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT request_json FROM generation_jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
        if not row or not row["request_json"]:
            return None
        return json.loads(row["request_json"])

    def recent(self, limit: int = 10) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit, 50))
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT job_id, job_json, created_at, updated_at
                FROM generation_jobs
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()
        return [
            {
                "job_id": row["job_id"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                **json.loads(row["job_json"]),
            }
            for row in rows
        ]

    def prune(self, max_records: int = 100) -> int:
        """只清理超出上限的已结束任务，运行中的任务不会被删除。"""
        safe_max = max(20, max_records)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT job_id, job_json
                FROM generation_jobs
                ORDER BY updated_at DESC
                """
            ).fetchall()
            removable = []
            for row in rows[safe_max:]:
                job = json.loads(row["job_json"])
                if job.get("status") in {"succeeded", "failed"}:
                    removable.append((row["job_id"],))
            if removable:
                connection.executemany(
                    "DELETE FROM generation_jobs WHERE job_id = ?",
                    removable,
                )
        return len(removable)

    def mark_interrupted(self) -> None:
        """把上次进程遗留的运行态标成中断，避免界面无限等待。"""
        for item in self.recent(limit=50):
            if item.get("status") not in {"pending", "running"}:
                continue
            job_id = item.pop("job_id")
            item.pop("created_at", None)
            item.pop("updated_at", None)
            item["status"] = "failed"
            item["message"] = "本机服务曾在任务执行中重启，请单独重试失败项"
            branches = item.get("branches") or {}
            for branch in branches.values():
                if branch.get("status") in {"pending", "running"}:
                    branch.update(
                        status="failed",
                        message="本机服务重启，当前分支未完成",
                    )
            self.save(job_id, item)
