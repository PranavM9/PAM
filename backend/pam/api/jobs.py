"""Import jobs for the REST API: an in-memory registry and the M1 -> M5 pipeline runner (SPEC §8 M13)."""

from __future__ import annotations

import logging
import shutil
import threading
from pathlib import Path

from pam.contracts.common import Source
from pam.contracts.reports import ImportReport, JobStatus
from pam.core.errors import PamError
from pam.core.ids import new_uuid
from pam.core.vault import Vault

log = logging.getLogger(__name__)

# Progress reached when a stage starts; "done" is 1.0. Progress never decreases.
STAGE_PROGRESS = {
    "queued": 0.0,
    "extract": 0.1,
    "normalize": 0.3,
    "derive": 0.5,
    "index": 0.7,
    "cluster": 0.9,
    "done": 1.0,
}


class JobRegistry:
    """Thread-safe in-memory store of `JobStatus` snapshots keyed by `job_id`.

    Behavior:
        Each update replaces the stored snapshot, so a status returned earlier never changes.
        Jobs are lost on restart.
    """

    def __init__(self) -> None:
        self._jobs: dict[str, JobStatus] = {}
        self._lock = threading.Lock()

    def create(self) -> JobStatus:
        """Register a new job in the `queued` stage and return its status."""
        job = JobStatus(job_id=new_uuid().hex, stage="queued", progress=0.0)
        with self._lock:
            self._jobs[job.job_id] = job
        return job

    def get(self, job_id: str) -> JobStatus | None:
        """Return the job's current status, or `None` for an unknown id."""
        with self._lock:
            return self._jobs.get(job_id)

    def update(self, job_id: str, **fields: object) -> JobStatus:
        """Replace fields of a job's status and return the new snapshot."""
        with self._lock:
            job = self._jobs[job_id].model_copy(update=fields)
            self._jobs[job_id] = job
            return job


def save_upload(chunks, directory: Path, filename: str) -> Path:
    """Write uploaded bytes to `directory/<filename>` and return the path.

    Behavior:
        Only the final path component of `filename` is used, so an upload cannot choose its
        folder. The name is kept because the archive in `imports/` is named after it.
    Exceptions:
        PamError: The upload is empty.
    Returns:
        The path of the saved file.
    Parameters:
        chunks: Iterable of byte chunks.
        directory: Existing folder to write into.
        filename: Client-supplied file name.
    """
    name = Path(filename.replace("\\", "/")).name or "export"
    path = directory / name
    size = 0
    with path.open("wb") as out:
        for chunk in chunks:
            size += len(chunk)
            out.write(chunk)
    if size == 0:
        raise PamError("uploaded file is empty", exit_code=2)
    return path


def run_import(
    registry: JobRegistry,
    job_id: str,
    vault: Vault,
    upload: Path,
    source: str,
    agent: str,
    cleanup: Path | None = None,
) -> None:
    """Run the import pipeline for one job and record each stage in the registry.

    Behavior:
        Runs extract, normalize (write episodes), derive, index and cluster in order and sets the
        job's `stage` and `progress` before each one. Any exception ends the job in the `error`
        stage with its message; nothing is raised to the caller. The `cleanup` folder is always
        removed.
    Parameters:
        registry: Job registry.
        job_id: Job to update.
        vault: Target vault.
        upload: Saved export file.
        source: `auto`, `claude`, `chatgpt` or `gemini`.
        agent: Agent scope that owns the episodes.
        cleanup: Temporary folder to delete when the job ends.
    """
    # Imported here: the pipeline modules pull in spaCy, numpy and the embedder.
    from pam.cluster.cluster import run_cluster  # noqa: PLC0415
    from pam.extract.derive import derive  # noqa: PLC0415
    from pam.importers.detect import extract  # noqa: PLC0415
    from pam.index.indexer import index_vault  # noqa: PLC0415
    from pam.normalize.writer import write_episodes  # noqa: PLC0415

    def stage(name: str) -> None:
        registry.update(job_id, stage=name, progress=STAGE_PROGRESS[name])

    try:
        stage("extract")
        conversations, parse_errors, selected = extract(upload, source)
        stage("normalize")
        written = write_episodes(vault, conversations, Source(selected), upload, agent)
        report: ImportReport = written.model_copy(update={"errors": [*parse_errors, *written.errors]})
        stage("derive")
        derive(vault)
        stage("index")
        index_vault(vault)
        stage("cluster")
        run_cluster(vault, agent)
        registry.update(job_id, stage="done", progress=1.0, report=report)
    except Exception as exc:  # noqa: BLE001 - a job never raises; its failure is its status
        log.warning("import job %s failed: %s", job_id, exc, exc_info=not isinstance(exc, PamError))
        message = str(exc) if isinstance(exc, PamError) else f"{type(exc).__name__}: {exc}"
        current = registry.get(job_id)
        registry.update(job_id, stage="error", progress=current.progress if current else 0.0, error=message)
    finally:
        if cleanup is not None:
            shutil.rmtree(cleanup, ignore_errors=True)
