"""
Compatibility layer.
The previous raw-market strategy has been retired.
All signal decisions now use the single fixed EMA20 + EMA200 + RSI + Volume strategy
implemented by mega_v4_engine.py. There is no reverse/contrarian strategy.
"""
from mega_v4_engine import (
    scan as _mega_scan,
    latest_price,
    start as _mega_start,
    status as _mega_status,
    _score,
)

def analyze_symbol(symbol, frame="15m", futures=False):
    return _score(symbol, "futures" if futures else "spot", frame)

def scan(frame="15m", limit=50, futures=False):
    return _mega_scan("futures" if futures else "spot", frame, limit)

def start_engine():
    return _mega_start()

def status():
    return _mega_status()
