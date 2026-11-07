from datetime import datetime
from enum import StrEnum
from pydantic import BaseModel, ConfigDict, Field


class Direction(StrEnum):
    BULLISH = "صاعد"
    BEARISH = "هابط"
    NEUTRAL = "محايد"


class MarketSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    market: str
    direction: Direction = Direction.NEUTRAL
    assets_scanned: int = Field(default=0, ge=0)
    opportunities: int = Field(default=0, ge=0)
    updated_at: datetime | None = None
    stale: bool = True


class TradeLevels(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    side: str
    timeframe: str = "15m"
    entry: float = Field(gt=0)
    stop_loss: float = Field(gt=0)
    take_profit_1: float = Field(gt=0)
    take_profit_2: float = Field(gt=0)
    take_profit_3: float = Field(gt=0)
    quality_score: int = Field(ge=0, le=100)
    rationale: list[str] = Field(default_factory=list)
