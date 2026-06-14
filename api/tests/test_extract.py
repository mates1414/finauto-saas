import io
import pytest
from unittest.mock import MagicMock, patch
from finauto_api.models import Job, Snapshot
from finauto.schemas import CompanyFinancials, FiscalYearData, IncomeStatement, BalanceSheet, CashFlowItems


def get_mock_financials(ticker="THYAO.IS"):
    return CompanyFinancials(
        ticker=ticker,
        name="Mock Airline Inc",
        currency="TRY",
        units="thousands",
        periods=[
            FiscalYearData(
                year=2023,
                income_statement=IncomeStatement(
                    revenue=100000.0,
                    cogs=80000.0,
                    gross_profit=20000.0,
                    sga=5000.0,
                    ebitda=15000.0,
                    depreciation_amortization=3000.0,
                    ebit=12000.0,
                    net_interest_expense=1000.0,
                    net_income=8000.0
                ),
                balance_sheet=BalanceSheet(
                    cash_and_equivalents=5000.0,
                    total_current_assets=15000.0,
                    total_assets=50000.0,
                    short_term_debt=2000.0,
                    long_term_debt=8000.0,
                    lease_liabilities=1000.0,
                    total_liabilities=25000.0,
                    total_equity=25000.0
                ),
                cash_flow=CashFlowItems(
                    depreciation_amortization=3000.0,
                    capex=2500.0
                )
            )
        ]
    )


def test_extract_endpoint(client, auth_headers):
    # Upload mock PDF file
    file_content = b"%PDF-1.4 Mock PDF Content"
    file_io = io.BytesIO(file_content)
    
    response = client.post(
        "/api/extract",
        headers=auth_headers,
        data={"ticker": "THYAO.IS"},
        files={"files": ("report.pdf", file_io, "application/pdf")}
    )
    
    assert response.status_code == 202
    data = response.json()
    assert data["type"] == "extract"
    assert data["status"] == "pending"
    assert "id" in data


@pytest.mark.asyncio
@patch("finauto_api.jobs.tasks.get_extractor")
async def test_extraction_task_execution(mock_get_extractor, db):
    # Setup mock extractor
    mock_extractor_instance = MagicMock()
    mock_extractor_instance.extract.return_value = get_mock_financials("THYAO.IS")
    mock_get_extractor.return_value = mock_extractor_instance
    
    # 1. Create a dummy user and job
    from finauto_api.models import User, Job
    user = User(email="task@example.com", hashed_password="hashedpassword")
    db.add(user)
    db.commit()
    
    # Save a fake uploaded file to testing local storage
    from finauto_api.deps import get_storage_dep
    storage = get_storage_dep()
    file_key = f"uploads/{user.id}/pdfs/test_report.pdf"
    storage.save_file(file_key, io.BytesIO(b"%PDF-1.4 Fake PDF"))
    
    job = Job(
        user_id=user.id,
        type="extract",
        status="pending",
        input_file_keys=file_key,
        ticker="THYAO.IS",
    )
    db.add(job)
    db.commit()
    
    # 2. Run the task
    from finauto_api.jobs.tasks import run_extraction_task
    await run_extraction_task(job.id)
    
    # 3. Assert status is updated and snapshot is created
    db.refresh(job)
    assert job.status == "completed"
    assert job.error is None
    assert "Mock Airline Inc" in job.result_json
    
    snapshot = db.query(Snapshot).filter(Snapshot.user_id == user.id, Snapshot.ticker == "THYAO.IS").first()
    assert snapshot is not None
    assert snapshot.name == "Mock Airline Inc"
    assert snapshot.financials_json is not None

