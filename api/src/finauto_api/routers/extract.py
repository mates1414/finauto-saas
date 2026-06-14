import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from ..deps import get_current_user, get_db, get_queue_dep, get_storage_dep
from ..models import Job, User
from ..storage import Storage
from ..jobs.queue import JobQueue
from pydantic import BaseModel, ConfigDict
import datetime

router = APIRouter(prefix="/api", tags=["extract"])

class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    type: str
    status: str
    error: Optional[str] = None
    result_json: Optional[str] = None
    created_at: datetime.datetime
    updated_at: datetime.datetime

@router.post("/extract", response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED)
async def extract_financials(
    ticker: str = Form(..., description="Target company ticker, e.g. BIMAS.IS"),
    files: List[UploadFile] = File(..., description="PDF files containing financial reports"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    storage: Storage = Depends(get_storage_dep),
    queue: JobQueue = Depends(get_queue_dep),
):
    if not files:
        raise HTTPException(status_code=400, detail="At least one PDF file is required.")

    file_keys = []
    for f in files:
        # Generate unique storage key
        unique_id = uuid.uuid4().hex
        file_key = f"uploads/{current_user.id}/pdfs/{unique_id}_{f.filename}"
        storage.save_file(file_key, f.file)
        file_keys.append(file_key)

    # Create job in database
    job = Job(
        user_id=current_user.id,
        type="extract",
        status="pending",
        input_file_keys=",".join(file_keys),
        ticker=ticker,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    # Enqueue job
    await queue.enqueue_extraction(job.id)

    return job

@router.get("/jobs/{job_id}", response_model=JobResponse)
def get_job_status(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = db.query(Job).filter(Job.id == job_id, Job.user_id == current_user.id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job
