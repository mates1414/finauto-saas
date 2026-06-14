from unittest.mock import MagicMock, patch
from finauto.schemas import PeerSuggestionSet, PeerCandidate
from finauto_api.models import Snapshot


def get_mock_suggestions(ticker="THYAO.IS"):
    return PeerSuggestionSet(
        target=ticker,
        candidates=[
            PeerCandidate(
                name="Pegasus Hava Tasimaciligi AS",
                ticker="PGSUS.IS",
                exchange="BIST",
                confidence=0.95,
                resolved=True,
                market_cap=50_000_000.0
            ),
            PeerCandidate(
                name="Tav Havalimanlari Holding AS",
                ticker="TAVHL.IS",
                exchange="BIST",
                confidence=0.88,
                resolved=True,
                market_cap=25_000_000.0
            )
        ],
        dropped=["FAKE.IS: Unverified ticker"],
        source="gemini discover"
    )


@patch("finauto_api.routers.peers.get_peer_researcher")
@patch("finauto_api.routers.peers.resolve_and_validate")
def test_suggest_peers_endpoint(mock_resolve, mock_get_researcher, client, auth_headers, db):
    # Setup mocks
    mock_researcher = MagicMock()
    mock_get_researcher.return_value = mock_researcher
    
    mock_suggestions = get_mock_suggestions("THYAO.IS")
    mock_researcher.discover.return_value = mock_suggestions
    mock_resolve.return_value = mock_suggestions

    # Execute request
    response = client.post(
        "/api/peers/suggest",
        headers=auth_headers,
        json={
            "ticker": "THYAO.IS",
            "name": "Turkish Airlines",
            "sector": "Airlines",
            "count": 3
        }
    )

    assert response.status_code == 200
    data = response.json()
    assert data["target"] == "THYAO.IS"
    assert len(data["candidates"]) == 2
    assert data["candidates"][0]["ticker"] == "PGSUS.IS"
    assert data["candidates"][0]["resolved"] is True
    assert len(data["dropped"]) == 1

    # Verify Snapshot peer list updated
    # Fetch test user id
    from finauto_api.models import User
    user = db.query(User).filter(User.email == "test@example.com").first()
    
    snapshot = db.query(Snapshot).filter(
        Snapshot.user_id == user.id,
        Snapshot.ticker == "THYAO.IS"
    ).first()
    
    assert snapshot is not None
    assert "PGSUS.IS" in snapshot.peers_json
    assert "TAVHL.IS" in snapshot.peers_json
