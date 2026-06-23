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
    """List the fiscal years cached (globally or privately in user's snapshot) for a ticker, so the UI can offer reuse."""
    ticker = ticker.upper()
    
    # 1. Fetch from global cache
    rows = (
        db.query(CachedFinancials)
        .filter(CachedFinancials.ticker == ticker)
        .order_by(CachedFinancials.fiscal_year.asc())
        .all()
    )

    # 2. Fetch from user's private snapshot
    snapshot = (
        db.query(Snapshot)
        .filter(Snapshot.user_id == current_user.id, Snapshot.ticker == ticker)
        .first()
    )

    snapshot_years = []
    snapshot_name = None
    snapshot_currency = None
    snapshot_units = None
    if snapshot and snapshot.financials_json:
        try:
            cf = CompanyFinancials.model_validate_json(snapshot.financials_json)
            snapshot_name = cf.name
            snapshot_currency = cf.currency
            snapshot_units = cf.units
            for period in cf.periods:
                snapshot_years.append(
                    CachedYear(
                        year=period.year,
                        source="private_snapshot",
                        updated_at=snapshot.created_at.isoformat() if snapshot.created_at else None
                    )
                )
        except Exception:
            pass

    # Merge and deduplicate by year
    years_dict = {}
    for r in rows:
        years_dict[r.fiscal_year] = CachedYear(
            year=r.fiscal_year,
            source=r.source,
            updated_at=r.updated_at.isoformat() if r.updated_at else None,
        )
    for sy in snapshot_years:
        if sy.year not in years_dict:
            years_dict[sy.year] = sy

    sorted_years = [years_dict[y] for y in sorted(years_dict.keys())]

    # Metadata comes from the most recently updated global row, or fallback to snapshot
    latest = max(rows, key=lambda r: r.updated_at, default=None)
    
    return AvailableResponse(
        ticker=ticker,
        name=(latest.name if latest else None) or snapshot_name,
        currency=(latest.currency if latest else None) or snapshot_currency,
        units=(latest.units if latest else None) or snapshot_units,
        years=sorted_years,
    )


@router.post("/{ticker}/select", response_model=dict)
def select_financials(
    ticker: str,
    req: SelectRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Reuse cached financials (global or user's private snapshot): assemble the chosen years and store them in the user's Snapshot."""
    ticker = ticker.upper()
    if not req.years:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Select at least one fiscal year.",
        )

    # 1. Fetch from global cache
    rows = (
        db.query(CachedFinancials)
        .filter(
            CachedFinancials.ticker == ticker,
            CachedFinancials.fiscal_year.in_(req.years),
        )
        .all()
    )

    # 2. Fetch missing years from user's private snapshot
    found_years = {r.fiscal_year for r in rows}
    missing_years = set(req.years) - found_years

    snapshot_periods = []
    snapshot_source = "private_snapshot"
    snapshot_name = None
    snapshot_currency = None
    snapshot_units = None

    if missing_years:
        snapshot = (
            db.query(Snapshot)
            .filter(Snapshot.user_id == current_user.id, Snapshot.ticker == ticker)
            .first()
        )
        if snapshot and snapshot.financials_json:
            try:
                cf = CompanyFinancials.model_validate_json(snapshot.financials_json)
                snapshot_name = cf.name
                snapshot_currency = cf.currency
                snapshot_units = cf.units
                snapshot_source = cf.source or "private_snapshot"
                for period in cf.periods:
                    if period.year in missing_years:
                        snapshot_periods.append(period)
            except Exception:
                pass

    # Assemble all period data
    all_year_data = []
    for r in rows:
        all_year_data.append({
            "year": r.fiscal_year,
            "currency": r.currency or "TRY",
            "units": r.units or "units",
            "source": r.source,
            "name": r.name,
            "sector_hint": r.sector_hint,
            "period": FiscalYearData.model_validate_json(r.period_json)
        })
    for p in snapshot_periods:
        all_year_data.append({
            "year": p.year,
            "currency": snapshot_currency or "TRY",
            "units": snapshot_units or "units",
            "source": snapshot_source,
            "name": snapshot_name,
            "sector_hint": None,
            "period": p
        })

    if len(all_year_data) != len(req.years):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Some requested years could not be found in global cache or private snapshot.",
        )

    # Currencies must agree — mixing currencies in one model would be silently wrong
    currencies = {y["currency"] for y in all_year_data}
    if len(currencies) > 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Selected years use mixed currencies {sorted(currencies)}; cannot combine.",
        )
    currency = currencies.pop()

    distinct_units = {y["units"] for y in all_year_data}
    if len(distinct_units) == 1:
        units = distinct_units.pop()
        periods = [y["period"] for y in all_year_data]
    else:
        units = "units"
        periods = [
            CompanyFinancials(
                ticker=ticker,
                currency=currency,
                units=y["units"],
                periods=[y["period"]],
            )
            .normalized()
            .periods[0]
            for y in all_year_data
        ]

    latest = max(all_year_data, key=lambda y: y["year"])
    
    assembled = CompanyFinancials(
        ticker=ticker,
        name=latest["name"] or snapshot_name,
        currency=currency,
        units=units,
        sector_hint=latest["sector_hint"],
        source=latest["source"],
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
