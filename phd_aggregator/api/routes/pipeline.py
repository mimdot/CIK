"""api.routes.pipeline — trigger the aggregation pipeline (Sprint 04, A6 +
Sprint 06, B2).

Runs go through :mod:`core.tasks` — rq when Redis is available, an in-process
daemon thread otherwise — so the API no longer spawns its own threads. Job
status is tracked by :func:`core.tasks.get_job_status` and can be polled here
or via the dedicated ``/api/jobs/{job_id}`` endpoints.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query

from core import tasks

from api.schemas import PipelineRunOut, PipelineRunRequest

log = logging.getLogger("api.pipeline")

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])
jobs_router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.post("/run", response_model=PipelineRunOut, status_code=202)
def trigger_run(body: PipelineRunRequest) -> PipelineRunOut:
    if body.field:
        from core.config import list_field_profiles
        if body.field not in list_field_profiles():
            raise HTTPException(status_code=422,
                                detail=f"Unknown field profile: {body.field}")
    try:
        run_id = tasks.enqueue_pipeline_job(country=body.country,
                                            sources=body.sources,
                                            field=body.field,
                                            subfields=body.subfields,
                                            include_slow=body.include_slow)
    except RuntimeError as exc:
        raise HTTPException(status_code=429, detail=str(exc))
    return PipelineRunOut(status="started", run_id=run_id)


@router.get("/status")
def pipeline_status(run_id: str = Query(..., description="run id to poll")) -> dict:
    info = tasks.get_job_status(run_id)
    if info is None:
        raise HTTPException(status_code=404, detail="Unknown run_id")
    return info


# --- /api/jobs (Sprint 06, B2) ---------------------------------------------------
@jobs_router.get("/{job_id}")
def get_job(job_id: str) -> dict:
    """Job status for the rq job queue (mirrors /api/pipeline/status)."""
    info = tasks.get_job_status(job_id)
    if info is None:
        raise HTTPException(status_code=404, detail="Unknown job_id")
    return info


@jobs_router.delete("/{job_id}")
def delete_job(job_id: str) -> dict:
    """Cancel a job — queued or already running.

    A running crawl stops cooperatively: the source in flight finishes its
    current request, the rest are skipped, and everything found so far is
    still filtered, deduped and stored. Returns 200 once the request has
    landed (the run reports ``cancelled`` when it has finished saving),
    409 only if the job had already finished.
    """
    if tasks.cancel_job(job_id):
        return {"status": "cancelling", "job_id": job_id}
    info = tasks.get_job_status(job_id)
    if info is None:
        raise HTTPException(status_code=404, detail="Unknown job_id")
    raise HTTPException(status_code=409, detail="Job has already finished")
