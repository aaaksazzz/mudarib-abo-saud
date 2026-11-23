"""Compatibility adapter: US stocks and contracts now use the single STP reversal engine."""
import breakout_50_strategy as engine

STRATEGY_FINGERPRINT = engine.STRATEGY_FINGERPRINT
STRATEGY_NAME = engine.STRATEGY_NAME
STRATEGY_TOTAL = 7
MARKETS = ("us-stocks", "us-contracts")
TIMEFRAMES = engine.TIMEFRAMES
FRAME_PROFILES = engine.FRAME_PROFILES
INTERVAL_MS = engine.INTERVAL_MS
target_prices = engine.target_prices

def analyze(market, symbol, rows, timeframe="15m", market_bias=None, diagnostics=None, **kwargs):
    if market not in MARKETS:
        if diagnostics is not None:
            diagnostics["invalid_market_or_timeframe"] = diagnostics.get("invalid_market_or_timeframe", 0) + 1
        return None
    return engine.analyze(market, symbol, rows, timeframe=timeframe,
                          market_bias=market_bias, diagnostics=diagnostics, **kwargs)

def diagnostic_self_test():
    base = engine.diagnostic_self_test()
    checks = dict(base.get("checks", {}))
    checks["us_markets_supported"] = set(MARKETS) == {"us-stocks", "us-contracts"}
    return {"ok": base.get("ok", False) and checks["us_markets_supported"],
            "fingerprint": STRATEGY_FINGERPRINT, "checks": checks,
            "markets": list(MARKETS), "timeframes": list(TIMEFRAMES),
            "strategies": ["FALSE_BREAKOUT_CLOSE_REVERSAL", "CLOSED_CANDLE_CONFIRMATION",
                           "BREAK_CANDLE_STRUCTURAL_STOP", "TARGETS_1R_2R_3R"]}
