from fastapi import APIRouter, Depends, HTTPException, Request
from arq.jobs import Job, JobStatus

from ..auth import get_user_context, UserContext

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("/{job_id}")
async def get_job_status(
    job_id: str,
    request: Request,
    user_ctx: UserContext = Depends(get_user_context),
):
    """
    Poll the status of an ARQ background job.

    Returns one of: queued | in_progress | complete | not_found | failed

    When status == "complete" and the job succeeded, the result payload
    (invoice_id, warnings, etc.) is included under the "result" key.
    When status == "complete" but the job raised an exception, the error
    message is included under the "error" key.
    """
    arq_pool = request.app.state.arq_pool
    job = Job(job_id, arq_pool)
    status = await job.status()

    if status == JobStatus.not_found:
        raise HTTPException(404, "Job not found or result has expired")

    response = {"job_id": job_id, "status": status.value}

    if status == JobStatus.complete:
        info = await job.result_info()
        if info and info.success:
            response["result"] = info.result
        elif info:
            response["error"] = str(info.result)

    return response
