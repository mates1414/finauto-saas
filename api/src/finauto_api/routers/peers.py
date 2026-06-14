from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..deps import get_current_user, get_db
from ..models import Snapshot, User

# Import finauto libraries
from finauto.config import get_settings as get_finauto_settings
from finauto.marketdata.web_research import get_peer_researcher, resolve_and_validate
from finauto.schemas import PeerSuggestionSet

router = APIRouter(prefix="/api/peers", tags=["peers"])

class PeerSuggestRequest(BaseModel):
    ticker: str
    name: Optional[str] = None
    sector: Optional[str] = None
    count: int = 5


@router.post("/suggest", response_model=PeerSuggestionSet)
def suggest_peers(
    req: PeerSuggestRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    finauto_settings = get_finauto_settings()
    target = req.name or req.ticker

    try:
        # 1. Run web research to find peers
        researcher = get_peer_researcher(finauto_settings)
        suggestion = researcher.discover(target, sector=req.sector, n=req.count)
        
        # 2. Filter hallucinations via yahoo validation
        validated_suggestion = resolve_and_validate(suggestion)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Peer discovery failed: {str(e)}"
        )

    # 3. Create or update snapshot for this ticker
    snapshot = db.query(Snapshot).filter(
        Snapshot.user_id == current_user.id,
        Snapshot.ticker == req.ticker
    ).first()

    tickers_list = validated_suggestion.tickers()

    if not snapshot:
        snapshot = Snapshot(
            user_id=current_user.id,
            ticker=req.ticker,
            name=req.name,
            peers_json=json_dumps(tickers_list)
        )
        db.add(snapshot)
    else:
        snapshot.peers_json = json_dumps(tickers_list)
        if req.name:
            snapshot.name = req.name
    db.commit()

    return validated_suggestion


def json_dumps(data) -> str:
    import json
    return json.dumps(data)
