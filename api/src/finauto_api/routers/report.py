import json
import uuid
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import Optional

from .. import deps
from ..deps import (
    get_current_user,
    get_current_user_flexible,
    get_db,
    get_queue_dep,
    get_storage_dep,
)
from ..models import Job, User
from ..storage import Storage
from ..jobs.queue import JobQueue
from ..pubsub import pubsub
from pydantic import BaseModel, ConfigDict
import datetime

router = APIRouter(prefix="/api/report", tags=["report"])

class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    type: str
    status: str
    error: Optional[str] = None
    result_json: Optional[str] = None
    created_at: datetime.datetime
    updated_at: datetime.datetime

@router.post("", response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED)
async def generate_report(
    ticker: str = Form(..., description="Target company ticker, e.g. BIMAS.IS"),
    file: Optional[UploadFile] = File(None, description="Edited valuation Excel workbook"),
    workbook_job_id: Optional[str] = Form(None, description="Completed workbook build job ID to use as fallback"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    storage: Storage = Depends(get_storage_dep),
    queue: JobQueue = Depends(get_queue_dep),
):
    if file:
        unique_id = uuid.uuid4().hex
        file_key = f"uploads/{current_user.id}/xlsx/{unique_id}_{file.filename}"
        storage.save_file(file_key, file.file)
    elif workbook_job_id:
        build_job = db.query(Job).filter(
            Job.id == workbook_job_id,
            Job.user_id == current_user.id,
            Job.type == "build",
            Job.status == "completed"
        ).first()
        if not build_job or not build_job.output_file_key:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or incomplete workbook job ID."
            )
        file_key = build_job.output_file_key
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either an uploaded file or a workbook_job_id must be provided."
        )

    # Log this as a "report" Job in DB
    job = Job(
        user_id=current_user.id,
        type="report",
        status="pending",
        input_file_keys=file_key,
        ticker=ticker,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    # Enqueue report job
    await queue.enqueue_report(job.id)

    return job


@router.get("/{job_id}/stream")
async def stream_report(
    job_id: str,
    current_user: User = Depends(get_current_user_flexible),
    db: Session = Depends(get_db)
):
    job = db.query(Job).filter(Job.id == job_id, Job.user_id == current_user.id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    async def event_generator():
        # 1. If the job is already in a terminal state, yield the cached result and stop.
        #    Use the module-qualified session so test/runtime overrides of SessionLocal apply.
        local_db = deps.SessionLocal()
        try:
            current_job = local_db.query(Job).filter(Job.id == job_id).first()
            if current_job is None:
                # Job not visible in this session — never block the client forever.
                yield f"data: {json.dumps('Error: job not found')}\n\n"
                yield "data: [DONE]\n\n"
                return

            if current_job.status == "completed":
                if current_job.result_json:
                    try:
                        res = json.loads(current_job.result_json)
                        markdown = res.get("markdown", "")
                        # Yield the full text in one chunk
                        yield f"data: {json.dumps(markdown)}\n\n"
                    except Exception:
                        pass
                yield "data: [DONE]\n\n"
                return

            if current_job.status == "failed":
                yield f"data: {json.dumps(f'Error: {current_job.error}')}\n\n"
                yield "data: [DONE]\n\n"
                return
        finally:
            local_db.close()

        # 2. Otherwise, subscribe to the pubsub channel and yield tokens as the worker produces them.
        #    The worker publishes a terminal "[DONE]" sentinel, which ends the subscribe loop.
        async for token in pubsub.subscribe(job_id):
            yield f"data: {json.dumps(token)}\n\n"

        # Send final completion signal
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
