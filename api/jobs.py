"""Background job manager.

Integration Standard 3:
Anything slower than 2 seconds runs as a job:
POST returns 202 with a job_id;
GET /api/v1/jobs/{job_id} returns status (queued, running, succeeded, failed),
progress 0-100 and result links.
Optional callback URL, signed with HMAC-SHA256 in an X-IncuBrix-Signature header.
"""

from __future__ import annotations
import asyncio
import hashlib
import hmac
import json
import os
import time
import uuid
from typing import Dict, Any, Optional, Callable, Awaitable
from datetime import datetime, timezone
import httpx

from api.logging_config import logger


class JobStatus:
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class Job:
    def __init__(
        self,
        job_id: str,
        job_type: str,
        callback_url: Optional[str] = None,
        correlation_id: Optional[str] = None
    ):
        self.job_id = job_id
        self.job_type = job_type
        self.status = JobStatus.QUEUED
        self.progress = 0
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.updated_at = self.created_at
        self.callback_url = callback_url
        self.correlation_id = correlation_id
        self.result: Optional[Dict[str, Any]] = None
        self.error: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "job_type": self.job_type,
            "status": self.status,
            "progress": self.progress,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "result": self.result,
            "error": self.error
        }


class JobManager:
    def __init__(self, hmac_secret: str = "incubrix-secret-key"):
        self.jobs: Dict[str, Job] = {}
        self.hmac_secret = hmac_secret.encode("utf-8")

    def create_job(
        self,
        job_type: str,
        callback_url: Optional[str] = None,
        correlation_id: Optional[str] = None
    ) -> Job:
        job_id = f"job_{uuid.uuid4().hex[:12]}"
        job = Job(job_id, job_type, callback_url, correlation_id)
        self.jobs[job_id] = job
        logger.info(f"Created job {job_id} of type {job_type}", extra={"job_id": job_id, "correlation_id": correlation_id})
        return job

    def get_job(self, job_id: str) -> Optional[Job]:
        return self.jobs.get(job_id)

    def update_progress(self, job_id: str, progress: int, status: Optional[str] = None) -> None:
        job = self.jobs.get(job_id)
        if job:
            job.progress = max(0, min(100, progress))
            if status:
                job.status = status
            job.updated_at = datetime.now(timezone.utc).isoformat()

    def complete_job(self, job_id: str, result: Dict[str, Any]) -> None:
        job = self.jobs.get(job_id)
        if job:
            job.status = JobStatus.SUCCEEDED
            job.progress = 100
            job.result = result
            job.updated_at = datetime.now(timezone.utc).isoformat()
            logger.info(f"Job {job_id} succeeded", extra={"job_id": job_id, "correlation_id": job.correlation_id})
            if job.callback_url:
                asyncio.create_task(self._dispatch_webhook(job))

    def fail_job(self, job_id: str, error_dict: Dict[str, Any]) -> None:
        job = self.jobs.get(job_id)
        if job:
            job.status = JobStatus.FAILED
            job.error = error_dict
            job.updated_at = datetime.now(timezone.utc).isoformat()
            logger.error(f"Job {job_id} failed: {error_dict}", extra={"job_id": job_id, "correlation_id": job.correlation_id})
            if job.callback_url:
                asyncio.create_task(self._dispatch_webhook(job))

    async def _dispatch_webhook(self, job: Job) -> None:
        if not job.callback_url:
            return
        payload = json.dumps(job.to_dict()).encode("utf-8")
        signature = hmac.new(self.hmac_secret, payload, hashlib.sha256).hexdigest()
        headers = {
            "Content-Type": "application/json",
            "X-IncuBrix-Signature": signature
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(job.callback_url, content=payload, headers=headers)
        except Exception as e:
            logger.warning(f"Failed to deliver webhook for {job.job_id}: {e}")


job_manager = JobManager(os.getenv("HMAC_SECRET_KEY", "incubrix-secure-signature-secret-key-32ch"))

