import json
import io
import asyncio
import pytest
from unittest.mock import MagicMock, patch
from finauto_api.models import Snapshot, Job
from finauto_api.pubsub import pubsub
from test_extract import get_mock_financials
from test_workbook import get_mock_market_data


def get_mock_computed():
    return {
        "target_price": 350.0,
        "current_price": 300.0,
        "upside": 0.1667,
        "signal": "AL",
        "dcf_price": 360.0,
        "ev_ebitda_price": 340.0,
        "pe_price": 350.0,
        "ev_sales_price": 320.0,
        "wacc": 0.18,
        "cost_of_equity": 0.20,
        "cost_of_debt": 0.12,
        "fx_price": 10.5
    }


def test_report_endpoint(client, auth_headers):
    # Upload mock Excel file
    file_io = io.BytesIO(b"Fake Excel Workbook Bytes")
    response = client.post(
        "/api/report",
        headers=auth_headers,
        data={"ticker": "THYAO.IS"},
        files={"file": ("edited.xlsx", file_io, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    )

    assert response.status_code == 202
    data = response.json()
    assert data["type"] == "report"
    assert data["status"] == "pending"
    assert "id" in data


@patch("finauto_api.jobs.tasks.recalc")
@patch("finauto_api.jobs.tasks.read_inputs")
@patch("finauto_api.jobs.tasks.StreamingReportWriter.complete")
def test_report_task_and_streaming(mock_writer_complete, mock_read_inputs, mock_recalc, db, client, auth_headers):
    # Setup mocks
    mock_recalc.side_effect = lambda p: p
    
    financials = get_mock_financials("THYAO.IS")
    mock_read_inputs.return_value = (financials, None, get_mock_computed())
    
    # Custom mock writer behavior: return static mock report text
    def side_effect_complete(system, user, stream=True):
        return "Equity research report text."
        
    mock_writer_complete.side_effect = side_effect_complete

    # Create dummy user, snapshot and job in DB
    from finauto_api.models import User
    user = db.query(User).filter(User.email == "test@example.com").first()
    
    snapshot = Snapshot(
        user_id=user.id,
        ticker="THYAO.IS",
        name="Mock Airline Inc",
        financials_json=financials.model_dump_json(),
        market_json=get_mock_market_data("THYAO.IS").model_dump_json()
    )
    db.add(snapshot)
    
    # Save a fake Excel file in testing local storage
    from finauto_api.deps import get_storage_dep
    storage = get_storage_dep()
    file_key = f"uploads/{user.id}/xlsx/edited.xlsx"
    storage.save_file(file_key, io.BytesIO(b"Fake Excel Content"))
    
    job = Job(
        id="test_job_id",
        user_id=user.id,
        type="report",
        status="pending",
        input_file_keys=file_key,
        ticker="THYAO.IS",
    )
    db.add(job)
    db.commit()

    # Run the task to completion synchronously
    from finauto_api.jobs.tasks import run_report_task
    import asyncio
    asyncio.run(run_report_task(job.id))
    
    # Assert job is completed
    db.refresh(job)
    assert job.status == "completed"
    
    # Call the stream endpoint for the completed job (should return full report cached)
    response = client.get(
        f"/api/report/{job.id}/stream",
        headers=auth_headers
    )
    
    assert response.status_code == 200
    lines = response.content.decode("utf-8").split("\n\n")
    # Verify we got the cached output
    assert any("Equity research report text." in line for line in lines)
    assert any("[DONE]" in line for line in lines)


def test_report_with_workbook_job_id_fallback(db, client, auth_headers):
    from finauto_api.models import User
    user = db.query(User).filter(User.email == "test@example.com").first()
    
    # Create a mock build job that is completed
    build_job = Job(
        id="test_build_job_id",
        user_id=user.id,
        type="build",
        status="completed",
        output_file_key="workbooks/test/model.xlsx",
        ticker="THYAO.IS"
    )
    db.add(build_job)
    db.commit()

    # Trigger report generation with workbook_job_id
    response = client.post(
        "/api/report",
        headers=auth_headers,
        data={
            "ticker": "THYAO.IS",
            "workbook_job_id": build_job.id
        }
    )
    
    assert response.status_code == 202
    data = response.json()
    assert data["type"] == "report"
    assert data["status"] == "pending"
    
    # Verify the created job has input_file_key set to build_job.output_file_key
    report_job = db.query(Job).filter(Job.id == data["id"]).first()
    assert report_job.input_file_keys == "workbooks/test/model.xlsx"


@patch("finauto_api.jobs.tasks.run_research_task")
def test_research_endpoints(mock_run_research, client, auth_headers):
    # Trigger research build
    response = client.post(
        "/api/research/build",
        headers=auth_headers,
        data={"ticker": "THYAO.IS"}
    )
    assert response.status_code == 202
    data = response.json()
    assert data["type"] == "research"
    assert data["status"] == "pending"
    job_id = data["id"]

    # Get research job status
    response = client.get(
        f"/api/research/{job_id}",
        headers=auth_headers
    )
    assert response.status_code == 200
    assert response.json()["status"] == "pending"


@pytest.mark.asyncio
@patch("yfinance.Ticker")
@patch("finauto_api.jobs.tasks.StreamingReportWriter.complete")
async def test_research_task_execution(mock_writer_complete, mock_ticker, db):
    # Mock yfinance Ticker info
    mock_ticker_instance = MagicMock()
    mock_ticker_instance.info = {
        "longName": "Mock Company",
        "longBusinessSummary": "Summary details",
        "sector": "Technology",
        "industry": "Software"
    }
    mock_ticker.return_value = mock_ticker_instance

    mock_writer_complete.return_value = "Mock Research Report Output"

    from finauto_api.models import User
    user = User(email="research_task@example.com", hashed_password="hashedpassword")
    db.add(user)
    db.commit()

    job = Job(
        user_id=user.id,
        type="research",
        status="pending",
        ticker="THYAO.IS",
    )
    db.add(job)
    db.commit()

    from finauto_api.jobs.tasks import run_research_task
    await run_research_task(job.id)

    db.refresh(job)
    assert job.status == "completed"
    assert "Mock Research Report Output" in job.result_json

