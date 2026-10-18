"""`POST /api/imports` and `GET /api/imports/{job_id}`: background import jobs (SPEC §7.14, §8 M13)."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, UploadFile

from pam.agents.manifest import load_manifest
from pam.api.deps import get_jobs, get_vault
from pam.api.errors import NOT_FOUND, VALIDATION_ERROR, ApiError
from pam.api.jobs import JobRegistry, run_import, save_upload
from pam.contracts.reports import JobStatus
from pam.core.vault import Vault

router = APIRouter(tags=["imports"])

SOURCES = ("auto", "claude", "chatgpt", "gemini")
_CHUNK = 1 << 20


@router.post("/imports", response_model=JobStatus, status_code=202)
def create_import(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    source: str = Form("auto"),
    agent: str = Form("default"),
    vault: Vault = Depends(get_vault),
    jobs: JobRegistry = Depends(get_jobs),
) -> JobStatus:
    """Save an uploaded export and start an import job for it.

    Behavior:
        Validates `source` and `agent`, stores the upload in a temporary folder and queues the
        pipeline (extract, normalize, derive, index, cluster) as a background task. The response is
        the job in the `queued` stage; poll `GET /imports/{job_id}`.
    Exceptions:
        ApiError: `source` is not `auto`, `claude`, `chatgpt` or `gemini` (400), or the file is empty (400).
        PamError: The agent does not exist (404) or its name is invalid (400).
    Returns:
        The queued job's status.
    Parameters:
        background: FastAPI background task queue.
        file: The export ZIP or JSON.
        source: Provider, or `auto` to detect it.
        agent: Agent scope that owns the episodes.
        vault: The served vault.
        jobs: The job registry.
    """
    if source not in SOURCES:
        raise ApiError(400, VALIDATION_ERROR, f"source must be one of {', '.join(SOURCES)}")
    load_manifest(agent, vault)
    folder = Path(tempfile.mkdtemp(prefix="pam-import-"))
    try:
        path = save_upload(iter(lambda: file.file.read(_CHUNK), b""), folder, file.filename or "export")
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    job = jobs.create()
    background.add_task(run_import, jobs, job.job_id, vault, path, source, agent, folder)
    return job


@router.get("/imports/{job_id}", response_model=JobStatus)
def get_import(job_id: str, jobs: JobRegistry = Depends(get_jobs)) -> JobStatus:
    """Return the current status of an import job.

    Exceptions:
        ApiError: The job id is unknown (404).
    Returns:
        The job's status.
    Parameters:
        job_id: Id returned by `POST /imports`.
        jobs: The job registry.
    """
    job = jobs.get(job_id)
    if job is None:
        raise ApiError(404, NOT_FOUND, f"import job {job_id} not found")
    return job
