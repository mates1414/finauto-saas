"""Endpoints backing the "Use previous data" flow.

The :class:`CachedFinancials` table is a *global*, shared store of extracted statements
(one row per ticker + fiscal year). These endpoints let the frontend discover which years
are already cached for a ticker and reuse a chosen subset — materializing them into the
calling user's Snapshot — so a valuation can be built without re-running the LLM extractor.
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..deps import get_current_user, get_db
from ..models import CachedFinancials, Snapshot, User

from finauto.schemas import CompanyFinancials, FiscalYearData

router = APIRouter(prefix="/api/financials", tags=["financials"])


class CachedYear(BaseModel):
    year: int
    source: Optional[str] = None
    updated_at: Optional[str] = None


class AvailableResponse(BaseModel):
    ticker: str
    name: Optional[str] = None
    currency: Optional[str] = None
    units: Optional[str] = None
    years: List[CachedYear]


class SelectRequest(BaseModel):
    years: List[int]


@router.get("/{ticker}/available", response_model=AvailableResponse)
def available_financials(
    ticker: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List the fiscal years cached (globally) for a ticker, so the UI can offer reuse."""
    ticker = ticker.upper()
    rows = (
        db.query(CachedFinancials)
        .filter(CachedFinancials.ticker == ticker)
        .order_by(CachedFinancials.fiscal_year.asc())
        .all()
    )

    # Metadata comes from the most recently updated row (latest extraction wins).
    latest = max(rows, key=lambda r: r.updated_at, default=None)
    return AvailableResponse(
        ticker=ticker,
        name=latest.name if latest else None,
        currency=latest.currency if latest else None,
        units=latest.units if latest else None,
        years=[
            CachedYear(
                year=r.fiscal_year,
                source=r.source,
                updated_at=r.updated_at.isoformat() if r.updated_at else None,
            )
            for r in rows
        ],
    )


@router.post("/{ticker}/select", response_model=dict)
def select_financials(
    ticker: str,
    req: SelectRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Reuse cached financials: assemble the chosen years and store them in the user's Snapshot."""
    ticker = ticker.upper()
    if not req.years:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Select at least one fiscal year.",
        )

    rows = (
        db.query(CachedFinancials)
        .filter(
            CachedFinancials.ticker == ticker,
            CachedFinancials.fiscal_year.in_(req.years),
        )
        .all()
    )
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No cached financials found for the requested ticker/years.",
        )

    # Currencies must agree — mixing currencies in one model would be silently wrong
    # (invariant #5). Units may differ across filings; normalize those instead.
    currencies = {(r.currency or "TRY") for r in rows}
    if len(currencies) > 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Selected years use mixed currencies {sorted(currencies)}; cannot combine.",
        )
    currency = currencies.pop()

    distinct_units = {(r.units or "units") for r in rows}
    if len(distinct_units) == 1:
        # All years share a scale — keep periods as extracted.
        units = distinct_units.pop()
        periods = [FiscalYearData.model_validate_json(r.period_json) for r in rows]
    else:
        # Mixed scales (e.g. thousands + millions) — normalize each to absolute units
        # before combining (invariant #10), reusing CompanyFinancials.normalized().
        units = "units"
        periods = [
            CompanyFinancials(
                ticker=ticker,
                currency=currency,
                units=(r.units or "units"),
                periods=[FiscalYearData.model_validate_json(r.period_json)],
            )
            .normalized()
            .periods[0]
            for r in rows
        ]

    latest = max(rows, key=lambda r: r.updated_at)
    assembled = CompanyFinancials(
        ticker=ticker,
        name=latest.name,
        currency=currency,
        units=units,
        sector_hint=latest.sector_hint,
        source=latest.source,
        periods=periods,
    ).with_deduped_periods()

    financials_json = assembled.model_dump_json(indent=2)

    snapshot = (
        db.query(Snapshot)
        .filter(Snapshot.user_id == current_user.id, Snapshot.ticker == ticker)
        .first()
    )
    if snapshot is None:
        snapshot = Snapshot(
            user_id=current_user.id,
            ticker=ticker,
            name=assembled.name,
            financials_json=financials_json,
        )
        db.add(snapshot)
    else:
        snapshot.name = assembled.name
        snapshot.financials_json = financials_json
    db.commit()

    return {
        "ticker": ticker,
        "name": assembled.name,
        "years_used": [p.year for p in assembled.sorted_periods()],
    }
