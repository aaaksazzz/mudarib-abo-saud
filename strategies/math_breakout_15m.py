"""Standalone pure-math 15m breakout strategy for SMART TRADING PRO.

No technical indicators, machine learning, or live order execution.
Input candles are Binance-style rows: [open_time, open, high, low, close, ...].
The signal is calculated only after a candle closes; execution is assumed at the
next candle open to avoid look-ahead bias.
"""
from dataclasses import dataclass
from typing import Literal, Sequence

Direction = Literal["BUY", "SELL"]

@dataclass(frozen=True)
class MathSignal:
    direction: Direction
    entry: float
    stop_loss: float
    take_profit: float
    risk_per_unit: float
    reward_risk: float
    signal_time: int
    entry_time: int

def calculate_signal(candles: Sequence[Sequence[float]], lookback: int = 20, reward_risk: float = 2.0) -> MathSignal | None:
    """Return the latest confirmed mathematical breakout, or None.

    Supply at least lookback + 2 candles: prior range candles, closed signal
    candle, then next candle used for simulated entry at its open.
    """
    if lookback < 2 or reward_risk <= 0 or len(candles) < lookback + 2:
        return None
    signal_index = len(candles) - 2
    entry_index = len(candles) - 1
    prior = candles[signal_index - lookback:signal_index]
    signal_candle = candles[signal_index]
    entry_candle = candles[entry_index]
    try:
        upper = max(float(c[2]) for c in prior)
        lower = min(float(c[3]) for c in prior)
        close = float(signal_candle[4])
        entry = float(entry_candle[1])
        signal_time = int(signal_candle[0])
        entry_time = int(entry_candle[0])
    except (IndexError, TypeError, ValueError):
        return None
    if min(upper, lower, close, entry) <= 0 or upper <= lower:
        return None
    if close > upper:
        direction: Direction = "BUY"
        stop = lower
        risk = entry - stop
        target = entry + reward_risk * risk
    elif close < lower:
        direction = "SELL"
        stop = upper
        risk = stop - entry
        target = entry - reward_risk * risk
    else:
        return None
    if risk <= 0 or target <= 0:
        return None
    return MathSignal(direction, entry, stop, target, risk, reward_risk, signal_time, entry_time)

def net_return_pct(direction: Direction, entry: float, exit_price: float, fee_each_side_pct: float = 0.1) -> float:
    """Arithmetic trade return after entry and exit fees; assumes no leverage."""
    if entry <= 0 or exit_price <= 0 or fee_each_side_pct < 0:
        raise ValueError("Prices must be positive and fee cannot be negative")
    gross = (exit_price - entry) / entry if direction == "BUY" else (entry - exit_price) / entry
    return gross * 100.0 - 2.0 * fee_each_side_pct
