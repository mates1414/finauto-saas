"""Tests for the shared financials cache + "Use previous data" reuse flow.

No live LLM/network: extraction is driven through a mocked extractor (mirroring
``test_extract.py``) and the reuse endpoints read a directly-seeded cache table.
"""

import io

import pytest
from unittest.mock import MagicMock, patch

from finauto_api.models import CachedFinancials, Job, Snapshot, User
from finauto.schemas import (
    BalanceSheet,
    CashFlowItems,
    CompanyFinancials,
    FiscalYearData,
    IncomeStatement,
)


def _financials(
    ticker="THYAO.IS",
    year=2023,
    *,
    revenue=100000.0,
    capex=2500.0,
    units="thousands",
    name="Mock Airline Inc",
):
    return CompanyFinancials(
        ticker=ticker,
        name=name,
        currency="TRY",
        units=units,
        source="mock:test-model",
        periods=[
            FiscalYearData(
                year=year,
                income_statement=IncomeStatement(revenue=revenue, ebitda=15000.0),
                balance_sheet=BalanceSheet(total_assets=50000.0, total_equity=25000.0),
                cash_flow=CashFlowItems(capex=capex),
            )
        ],
    )


def _seed_cache(
    db,
    ticker,
    year,
    *,
    units="thousands",
    revenue=100000.0,
    currency="TRY",
    name="Mock Co",
):
    period = FiscalYearData(
        year=year,
        income_statement=IncomeStatement(revenue=revenue),
        balance_sheet=BalanceSheet(),
        cash_flow=CashFlowItems(),
    )
    row = CachedFinancials(
        ticker=ticker,
        fiscal_year=year,
        source="mock:test-model",
        name=name,
        currency=currency,
        units=units,
        period_json=period.model_dump_json(),
    )
    db.add(row)
    db.commit()
    return row


async def _run_extraction(db, mock_financials):
    """Create a user + extract job, stub a fake PDF, and run the extraction task."""
    user = User(email=f"u{id(mock_financials)}@example.com", hashed_password="x")
    db.add(user)
    db.commit()

    from finauto_api.deps import get_storage_dep

    storage = get_storage_dep()
    file_key = f"uploads/{user.id}/pdfs/test_report.pdf"
    storage.save_file(file_key, io.BytesIO(b"%PDF-1.4 Fake PDF"))

    job = Job(
        user_id=user.id,
        type="extract",
        status="pending",
        input_file_keys=file_key,
        ticker=mock_financials.ticker,
    )
    db.add(job)
    db.commit()

    with patch("finauto_api.jobs.tasks.get_extractor") as mock_get_extractor:
        instance = MagicMock()
        instance.extract.return_value = mock_financials
        mock_get_extractor.return_value = instance
        from finauto_api.jobs.tasks import run_extraction_task

        await run_extraction_task(job.id)

    db.refresh(job)
    return user, job


@pytest.mark.asyncio
async def test_extraction_populates_cache(db):
    await _run_extraction(db, _financials(year=2023, revenue=100000.0))

    rows = (
        db.query(CachedFinancials).filter(CachedFinancials.ticker == "THYAO.IS").all()
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.fiscal_year == 2023
    assert row.units == "thousands"
    period = FiscalYearData.model_validate_json(row.period_json)
    assert period.income_statement.revenue == 100000.0
    assert period.cash_flow.capex == 2500.0


@pytest.mark.asyncio
async def test_cache_merge_fills_blanks_without_overwriting(db):
    # First extraction: revenue set, capex missing.
    await _run_extraction(db, _financials(year=2023, revenue=100000.0, capex=None))
    # Second extraction (same year): different revenue + a capex value.
    await _run_extraction(db, _financials(year=2023, revenue=999.0, capex=500.0))

    rows = (
        db.query(CachedFinancials).filter(CachedFinancials.ticker == "THYAO.IS").all()
    )
    assert len(rows) == 1  # still one row per (ticker, year)
    period = FiscalYearData.model_validate_json(rows[0].period_json)
    assert period.income_statement.revenue == 100000.0  # existing non-null preserved
    assert period.cash_flow.capex == 500.0  # blank filled from later extraction


def test_available_endpoint_lists_years(client, auth_headers, db):
    _seed_cache(db, "BIMAS.IS", 2022)
    _seed_cache(db, "BIMAS.IS", 2023)

    resp = client.get("/api/financials/BIMAS.IS/available", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ticker"] == "BIMAS.IS"
    assert [y["year"] for y in data["years"]] == [2022, 2023]


def test_available_endpoint_empty_when_uncached(client, auth_headers):
    resp = client.get("/api/financials/NONE.IS/available", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["years"] == []


def test_select_materializes_snapshot(client, auth_headers, db):
    _seed_cache(db, "BIMAS.IS", 2022, revenue=80000.0)
    _seed_cache(db, "BIMAS.IS", 2023, revenue=100000.0)

    resp = client.post(
        "/api/financials/BIMAS.IS/select",
        headers=auth_headers,
        json={"years": [2023]},
    )
    assert resp.status_code == 200
    assert resp.json()["years_used"] == [2023]

    user = db.query(User).filter(User.email == "test@example.com").first()
    snap = (
        db.query(Snapshot)
        .filter(Snapshot.user_id == user.id, Snapshot.ticker == "BIMAS.IS")
        .first()
    )
    assert snap is not None and snap.financials_json
    fin = CompanyFinancials.model_validate_json(snap.financials_json)
    assert [p.year for p in fin.sorted_periods()] == [2023]
    assert fin.latest.income_statement.revenue == 100000.0


def test_select_rejects_empty_year_list(client, auth_headers, db):
    _seed_cache(db, "BIMAS.IS", 2023)
    resp = client.post(
        "/api/financials/BIMAS.IS/select", headers=auth_headers, json={"years": []}
    )
    assert resp.status_code == 400


def test_select_404_when_years_uncached(client, auth_headers, db):
    _seed_cache(db, "BIMAS.IS", 2023)
    resp = client.post(
        "/api/financials/BIMAS.IS/select", headers=auth_headers, json={"years": [1999]}
    )
    assert resp.status_code == 404


def test_select_mixed_units_normalizes_to_absolute(client, auth_headers, db):
    # 2022 in thousands (100 -> 100_000) and 2023 in millions (1 -> 1_000_000).
    _seed_cache(db, "MIX.IS", 2022, units="thousands", revenue=100.0)
    _seed_cache(db, "MIX.IS", 2023, units="millions", revenue=1.0)

    resp = client.post(
        "/api/financials/MIX.IS/select",
        headers=auth_headers,
        json={"years": [2022, 2023]},
    )
    assert resp.status_code == 200

    user = db.query(User).filter(User.email == "test@example.com").first()
    snap = (
        db.query(Snapshot)
        .filter(Snapshot.user_id == user.id, Snapshot.ticker == "MIX.IS")
        .first()
    )
    fin = CompanyFinancials.model_validate_json(snap.financials_json)
    assert fin.units == "units"  # normalized because scales differed
    by_year = {p.year: p for p in fin.sorted_periods()}
    assert by_year[2022].income_statement.revenue == 100_000.0
    assert by_year[2023].income_statement.revenue == 1_000_000.0


def test_select_rejects_mixed_currencies(client, auth_headers, db):
    _seed_cache(db, "FX.IS", 2022, currency="TRY", revenue=100.0)
    _seed_cache(db, "FX.IS", 2023, currency="USD", revenue=10.0)

    resp = client.post(
        "/api/financials/FX.IS/select",
        headers=auth_headers,
        json={"years": [2022, 2023]},
    )
    assert resp.status_code == 400
