import io
from unittest.mock import MagicMock, patch
from finauto.schemas import MarketData, TickerSnapshot
from datetime import date
from finauto_api.models import Snapshot, Job
from test_extract import get_mock_financials


def get_mock_market_data(ticker="THYAO.IS"):
    return MarketData(
        target=TickerSnapshot(
            ticker=ticker,
            name="Mock Airline Inc",
            currency="TRY",
            price=300.0,
            shares_outstanding=1380000.0,
            market_cap=414000000.0,
            beta=1.1,
            total_debt=10000.0,
            cash=5000.0,
            ebitda=15000.0,
            revenue=100000.0,
            net_income=8000.0,
            sector="Industrials",
            industry="Airlines",
            as_of=date.today()
        ),
        peers=[
            TickerSnapshot(
                ticker="PGSUS.IS",
                name="Pegasus",
                currency="TRY",
                price=800.0,
                shares_outstanding=102290.0,
                market_cap=81832000.0,
                beta=1.2,
                total_debt=9000.0,
                cash=3000.0,
                ebitda=8000.0,
                revenue=30000.0,
                net_income=4000.0,
                sector="Industrials",
                industry="Airlines",
                as_of=date.today()
            )
        ]
    )


@patch("finauto_api.routers.workbook.fetch_market_data")
@patch("finauto_api.routers.workbook.check_sector")
def test_build_workbook_endpoint(mock_check_sector, mock_fetch_market_data, client, auth_headers, db):
    # Setup mocks
    mock_fetch_market_data.return_value = get_mock_market_data("THYAO.IS")
    mock_check_sector.return_value = None

    # Pre-populate Snapshot with financials
    from finauto_api.models import User
    user = db.query(User).filter(User.email == "test@example.com").first()
    
    financials = get_mock_financials("THYAO.IS")
    snapshot = Snapshot(
        user_id=user.id,
        ticker="THYAO.IS",
        name="Mock Airline Inc",
        financials_json=financials.model_dump_json()
    )
    db.add(snapshot)
    db.commit()

    # Call build endpoint
    response = client.post(
        "/api/workbook/build",
        headers=auth_headers,
        json={
            "ticker": "THYAO.IS",
            "peers": ["PGSUS.IS"],
            "assumptions": {},
            "locale": "tr"
        }
    )

    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "completed"
    assert data["ticker"] == "THYAO.IS"
    assert "job_id" in data

    # Verify Job is created in DB
    job_id = data["job_id"]
    job = db.query(Job).filter(Job.id == job_id).first()
    assert job is not None
    assert job.type == "build"
    assert job.status == "completed"
    assert job.output_file_key is not None

    # Test download endpoint
    download_response = client.get(
        f"/api/workbook/{job_id}",
        headers=auth_headers
    )
    assert download_response.status_code == 200
    assert download_response.headers["content-type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert len(download_response.content) > 0
