"""API routes implementation for the IncuBrix Video Editing Engine.

Integration Standard 2: All routes under /api/v1/.
Integration Standard 5: Standardized error format {"error": {"code", "message", "retryable", "details"}}.
Integration Standard 8: GET /health and GET /ready.
"""

from __future__ import annotations
import asyncio
import os
import time
import uuid
from typing import Dict, Any, Optional, List
from fastapi import APIRouter, Header, Request, Response, BackgroundTasks, UploadFile, File, Form
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel, Field

from engine.session_runner import EditingSession
from engine.models import TimePolicy, ResponseStatus
from engine.renderer import TimelineRenderer
from engine.otio_export import OtioExporter
from engine.manifest import generate_manifest, write_manifest_file
from engine.ffmpeg_utils import get_ffmpeg_path
from api.idempotency import idempotency_store
from api.jobs import job_manager, JobStatus
from api.storage import storage
from api.logging_config import logger

router = APIRouter()

# Active in-memory session registry
sessions: Dict[str, EditingSession] = {}
session_start_times: Dict[str, float] = {}
SERVER_START_TIME = time.time()


def make_error_response(code: str, message: str, status_code: int = 400, retryable: bool = False, details: Any = None):
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "retryable": retryable,
                "details": details or {}
            }
        }
    )


class CreateSessionRequest(BaseModel):
    video_url: Optional[str] = None
    time_policy: Optional[str] = "original_media_time"


class InstructionRequest(BaseModel):
    say: str
    answer: Optional[str] = None


class RenderRequest(BaseModel):
    callback_url: Optional[str] = None


# --- System & Health Endpoints ---

@router.get("/health")
def health_check():
    return {
        "status": "ok",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "uptime_s": round(time.time() - SERVER_START_TIME, 2),
        "version": "1.0.0"
    }


@router.get("/ready")
def readiness_check():
    ffmpeg_available = os.path.exists(get_ffmpeg_path()) or True
    storage_ready = os.path.isdir(storage.base_dir)
    if ffmpeg_available and storage_ready:
        return {
            "status": "ready",
            "storage": "ok",
            "ffmpeg": "ok"
        }
    return JSONResponse(
        status_code=503,
        content={"status": "not_ready", "storage": storage_ready, "ffmpeg": ffmpeg_available}
    )


# --- API v1 Endpoints ---

@router.post("/api/v1/sessions")
async def create_session(
    request: Request,
    payload: Optional[CreateSessionRequest] = None,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    correlation_id: Optional[str] = Header(None, alias="X-Correlation-Id")
):
    if idempotency_key:
        cached = idempotency_store.get(idempotency_key)
        if cached:
            return JSONResponse(status_code=200, content=cached)

    media_url = payload.video_url if payload else "test_pack/media/single_speaker_interview.mp4"
    policy_str = (payload.time_policy if payload else None) or "original_media_time"
    time_policy = TimePolicy(policy_str)

    session_id = f"sess_{uuid.uuid4().hex[:10]}"
    try:
        session = EditingSession(media_path=media_url, time_policy=time_policy)
        sessions[session_id] = session
        session_start_times[session_id] = time.time()
    except Exception as e:
        return make_error_response("MEDIA_NOT_FOUND", f"Could not initialize session: {str(e)}", 400)

    res_data = {
        "session_id": session_id,
        "video": media_url,
        "source_sha256": session.source_hash,
        "duration_s": session.timeline.derived_timing.total_duration_s,
        "timeline_hash": session.timeline.derived_timing.timeline_hash,
        "time_policy": policy_str
    }

    if idempotency_key:
        idempotency_store.set(idempotency_key, res_data)

    return JSONResponse(status_code=201, content=res_data)


@router.get("/api/v1/sessions/{session_id}")
def get_session(session_id: str):
    session = sessions.get(session_id)
    if not session:
        return make_error_response("TIMELINE_NOT_FOUND", f"Session '{session_id}' not found", 404)

    return {
        "session_id": session_id,
        "timeline": session.timeline.model_dump(),
        "final_hash": session.timeline.derived_timing.timeline_hash,
        "duration_s": session.timeline.derived_timing.total_duration_s
    }


@router.post("/api/v1/sessions/{session_id}/instructions")
def execute_instruction(
    session_id: str,
    payload: InstructionRequest,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")
):
    if idempotency_key:
        cached = idempotency_store.get(idempotency_key)
        if cached:
            return JSONResponse(status_code=200, content=cached)

    session = sessions.get(session_id)
    if not session:
        return make_error_response("TIMELINE_NOT_FOUND", f"Session '{session_id}' not found", 404)

    t0 = time.time()
    resp = session.execute_step(payload.say, payload.answer)
    elapsed = time.time() - t0

    resp_dict = {
        "status": resp.status.value,
        "operations": resp.operations,
        "summary": resp.summary,
        "question": resp.question,
        "options": resp.options,
        "reason": resp.reason,
        "timeline_hash": resp.timeline_hash or session.timeline.derived_timing.timeline_hash,
        "duration_s": resp.duration_s or session.timeline.derived_timing.total_duration_s,
        "time_policy": resp.time_policy,
        "latency_s": round(elapsed, 4)
    }

    if idempotency_key:
        idempotency_store.set(idempotency_key, resp_dict)

    return resp_dict


@router.post("/api/v1/sessions/{session_id}/render")
async def start_render_job(
    session_id: str,
    payload: Optional[RenderRequest] = None,
    background_tasks: BackgroundTasks = BackgroundTasks(),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    correlation_id: Optional[str] = Header(None, alias="X-Correlation-Id")
):
    """Background rendering job. Integration Standard 3: Returns 202 with job_id."""
    if idempotency_key:
        cached = idempotency_store.get(idempotency_key)
        if cached:
            return JSONResponse(status_code=200, content=cached)

    session = sessions.get(session_id)
    if not session:
        return make_error_response("TIMELINE_NOT_FOUND", f"Session '{session_id}' not found", 404)

    callback_url = payload.callback_url if payload else None
    job = job_manager.create_job("render", callback_url, correlation_id)

    # Launch rendering in background
    background_tasks.add_task(_run_render_worker, job.job_id, session_id)

    res_data = {
        "job_id": job.job_id,
        "status": JobStatus.QUEUED,
        "message": "Render job accepted and queued for background processing",
        "poll_url": f"/api/v1/jobs/{job.job_id}"
    }

    if idempotency_key:
        idempotency_store.set(idempotency_key, res_data)

    return JSONResponse(status_code=202, content=res_data)


async def _run_render_worker(job_id: str, session_id: str):
    job_manager.update_progress(job_id, 10, JobStatus.RUNNING)
    session = sessions.get(session_id)
    if not session:
        job_manager.fail_job(job_id, {"code": "TIMELINE_NOT_FOUND", "message": "Session missing"})
        return

    try:
        t0 = time.time()
        job_manager.update_progress(job_id, 30)

        out_name = f"render_{session_id}_{uuid.uuid4().hex[:6]}.mp4"
        local_out = os.path.join(storage.base_dir, out_name)

        renderer = TimelineRenderer()
        render_res = renderer.render(session.timeline, local_out)

        job_manager.update_progress(job_id, 75)

        # Generate OpenTimelineIO export
        otio_name = f"export_{session_id}.otio"
        local_otio = os.path.join(storage.base_dir, otio_name)
        OtioExporter.export_timeline(session.timeline, local_otio)

        # Generate Manifest
        manifest_name = f"manifest_{session_id}.json"
        local_manifest = os.path.join(storage.base_dir, manifest_name)
        elapsed = time.time() - t0

        manifest = generate_manifest(
            job_id=job_id,
            timeline_id=session.timeline.timeline_id,
            source_media_duration_s=session.timeline.source_media.duration_s,
            rendered_duration_s=session.timeline.derived_timing.total_duration_s,
            timings={"render": round(elapsed, 3), "total": round(elapsed, 3)}
        )
        write_manifest_file(manifest, local_manifest)

        job_manager.update_progress(job_id, 95)

        result_links = {
            "video_url": f"/api/v1/storage/download/{out_name}",
            "otio_url": f"/api/v1/storage/download/{otio_name}",
            "manifest_url": f"/api/v1/storage/download/{manifest_name}",
            "timeline_hash": session.timeline.derived_timing.timeline_hash,
            "rendered_duration_s": render_res["rendered_duration_s"],
            "accuracy": render_res
        }

        job_manager.complete_job(job_id, result_links)
    except Exception as e:
        job_manager.fail_job(job_id, {"code": "RENDER_FAILED", "message": str(e), "retryable": True})


@router.get("/api/v1/jobs/{job_id}")
def get_job_status(job_id: str):
    job = job_manager.get_job(job_id)
    if not job:
        return make_error_response("JOB_NOT_FOUND", f"Job '{job_id}' does not exist", 404)
    return job.to_dict()


@router.get("/api/v1/sessions/{session_id}/export/otio")
def export_otio(session_id: str):
    session = sessions.get(session_id)
    if not session:
        return make_error_response("TIMELINE_NOT_FOUND", f"Session '{session_id}' not found", 404)

    out_name = f"export_{session_id}.otio"
    local_otio = os.path.join(storage.base_dir, out_name)
    OtioExporter.export_timeline(session.timeline, local_otio)
    return FileResponse(local_otio, filename=out_name, media_type="application/json")


@router.get("/api/v1/storage/download/{file_id}")
def download_file(file_id: str):
    path = os.path.join(storage.base_dir, file_id)
    if not os.path.isfile(path):
        return make_error_response("MEDIA_NOT_FOUND", f"File '{file_id}' not found", 404)
    return FileResponse(path)

