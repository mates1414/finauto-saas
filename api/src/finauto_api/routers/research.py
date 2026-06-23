import json
import uuid
from typing import Optional
from fastapi import APIRouter, Depends, Form, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel, ConfigDict
import datetime

from .. import deps
from ..deps import (
    get_current_user,
    get_current_user_flexible,
    get_db,
    get_queue_dep,
)
from ..models import Job, User
from ..jobs.queue import JobQueue
from ..pubsub import pubsub

router = APIRouter(prefix="/api/research", tags=["research"])

class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    type: str
    status: str
    error: Optional[str] = None
    result_json: Optional[str] = None
    created_at: datetime.datetime
    updated_at: datetime.datetime

@router.post("/build", response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED)
async def build_research(
    ticker: str = Form(..., description="Target company ticker, e.g. BIMAS.IS"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    queue: JobQueue = Depends(get_queue_dep),
):
    # Log this as a "research" Job in DB
    job = Job(
        user_id=current_user.id,
        type="research",
        status="pending",
        ticker=ticker,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    # Enqueue research job
    await queue.enqueue_research(job.id)

    return job

@router.get("/{job_id}", response_model=JobResponse)
def get_research_status(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = db.query(Job).filter(Job.id == job_id, Job.user_id == current_user.id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job

@router.get("/{job_id}/stream")
async def stream_research(
    job_id: str,
    current_user: User = Depends(get_current_user_flexible),
    db: Session = Depends(get_db)
):
    job = db.query(Job).filter(Job.id == job_id, Job.user_id == current_user.id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    async def event_generator():
        local_db = deps.SessionLocal()
        try:
            current_job = local_db.query(Job).filter(Job.id == job_id).first()
            if current_job is None:
                yield f"data: {json.dumps('Error: job not found')}\n\n"
                yield "data: [DONE]\n\n"
                return

            if current_job.status == "completed":
                if current_job.result_json:
                    try:
                        if current_job.result_json.strip().startswith("{"):
                            res = json.loads(current_job.result_json)
                            markdown = res.get("markdown", current_job.result_json)
                        else:
                            markdown = current_job.result_json
                        yield f"data: {json.dumps(markdown)}\n\n"
                    except Exception:
                        yield f"data: {json.dumps(current_job.result_json)}\n\n"
                yield "data: [DONE]\n\n"
                return

            if current_job.status == "failed":
                yield f"data: {json.dumps(f'Error: {current_job.error}')}\n\n"
                yield "data: [DONE]\n\n"
                return
        finally:
            local_db.close()

        async for token in pubsub.subscribe(job_id):
            yield f"data: {json.dumps(token)}\n\n"

        yield "data: [DONE]\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
