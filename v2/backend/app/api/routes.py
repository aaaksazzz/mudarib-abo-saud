from fastapi import APIRouter
from app.schemas.market import MarketSummary

router = APIRouter()


@router.get("/markets", response_model=list[MarketSummary])
async def list_markets() -> list[MarketSummary]:
    # Deliberately returns immediately; provider scans belong to the worker.
    return [
        MarketSummary(market=key)
        for key in (
            "binance-spot",
            "binance-futures",
            "binance-alpha",
            "us-stocks",
            "us-contracts",
            "saudi",
            "forex-gold",
        )
    ]


@router.get("/markets/{market}/snapshot", response_model=MarketSummary)
async def market_snapshot(market: str) -> MarketSummary:
    # Cache/repository integration is added before enabling live market output.
    return MarketSummary(market=market)
