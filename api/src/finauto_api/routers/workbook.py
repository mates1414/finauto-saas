import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session
from pathlib import Path

from ..config import settings
from ..deps import get_current_user, get_current_user_flexible, get_db, get_storage_dep
from ..models import Job, Snapshot, User
from ..storage import Storage

# Import finauto libraries
from finauto.assumptions import derive_assumptions
from finauto.engine.builder import build_workbook
from finauto.schemas import CompanyFinancials, ValuationInputs
from finauto.validation.sanity import reconcile_financials
from finauto.validation.sector_guard import SectorNotSupportedError, check_sector
from finauto.marketdata.yahoo import fetch_market_data

router = APIRouter(prefix="/api/workbook", tags=["workbook"])

class WorkbookBuildRequest(BaseModel):
    ticker: str
    peers: List[str]
    assumptions: Optional[dict] = None
    locale: str = "tr"
    industry: Optional[str] = None
    force: bool = False


@router.post("/build", response_model=dict, status_code=status.HTTP_201_CREATED)
def build_valuation_model(
    req: WorkbookBuildRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    storage: Storage = Depends(get_storage_dep),
):
    # 1. Load historical financials from Snapshot
    snapshot = db.query(Snapshot).filter(
        Snapshot.user_id == current_user.id,
        Snapshot.ticker == req.ticker
    ).first()

    if not snapshot or not snapshot.financials_json:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No historical financials found for this ticker. Extract PDFs first."
        )

    fin = CompanyFinancials.model_validate_json(snapshot.financials_json)

    # 2. Fetch Yahoo snapshot market data
    try:
        mkt = fetch_market_data(req.ticker, req.peers)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to fetch market data from Yahoo Finance: {str(e)}"
        )

    # 3. Enforce sector guard
    try:
        check_sector(mkt.target, force=req.force)
    except SectorNotSupportedError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )

    # Cache market data & peer list in snapshot
    snapshot.market_json = mkt.model_dump_json()
    snapshot.peers_json = json_dumps(req.peers)
    db.commit()

    # 4. Resolve Damodaran Industry Beta if requested
    industry_beta = None
    if req.industry:
        from finauto.marketdata.damodaran import find_industry
        beta_path = _resolve_beta_path()
        if beta_path is not None:
            try:
                industry_beta = find_industry(beta_path, req.industry)
            except Exception:
                # Degrade gracefully per CLI behavior
                pass

    # 5. Reconcile financials and build inputs
    fin_clean, notes = reconcile_financials(fin)
    asm = derive_assumptions(fin_clean, req.assumptions)

    inputs = ValuationInputs(
        financials=fin_clean,
        market=mkt,
        assumptions=asm,
        locale=req.locale,
        industry_beta=industry_beta
    )

    # 6. Generate workbook in memory / temp file
    import tempfile
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_file = Path(temp_dir) / f"{req.ticker.replace('.', '_')}_valuation.xlsx"
        build_workbook(inputs, temp_file)
        
        # Save generated spreadsheet to storage
        file_key = f"workbooks/{current_user.id}/{uuid.uuid4().hex}_valuation.xlsx"
        with open(temp_file, "rb") as f:
            storage.save_file(file_key, f)

    # 7. Log this as a "build" Job in DB
    job = Job(
        user_id=current_user.id,
        type="build",
        status="completed",
        output_file_key=file_key
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    return {"job_id": job.id, "ticker": req.ticker, "status": "completed"}


@router.get("/{job_id}")
def download_workbook(
    job_id: str,
    current_user: User = Depends(get_current_user_flexible),
    db: Session = Depends(get_db),
    storage: Storage = Depends(get_storage_dep),
):
    job = db.query(Job).filter(Job.id == job_id, Job.user_id == current_user.id, Job.type == "build").first()
    if not job or not job.output_file_key:
        raise HTTPException(status_code=404, detail="Valuation workbook not found")

    try:
        file_bytes = storage.get_file(job.output_file_key)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File missing from storage")

    filename = Path(job.output_file_key).name
    return Response(
        content=file_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


def _resolve_beta_path() -> Optional[Path]:
    """Locate Damodaran's betaemerg.xls without hardcoding a machine path.

    Order: explicit ``DAMODARAN_BETA_PATH`` config → alongside the installed
    finauto repo → current working directory. Returns ``None`` if not found.
    """
    if settings.damodaran_beta_path:
        p = Path(settings.damodaran_beta_path)
        return p if p.exists() else None
    try:
        import finauto
        # .../finauto/src/finauto/__init__.py -> repo root is two parents up from the package dir
        candidate = Path(finauto.__file__).resolve().parents[2] / "betaemerg.xls"
        if candidate.exists():
            return candidate
    except Exception:
        pass
    cwd = Path("betaemerg.xls")
    return cwd if cwd.exists() else None


def json_dumps(data) -> str:
    import json
    return json.dumps(data)
