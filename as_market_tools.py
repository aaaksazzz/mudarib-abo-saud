"""AS market/timeframe adapter for the imported trader-skill toolkit.

Universal portfolio/risk helpers are exposed across all AS markets and frames.
SEC/13F/Congress/US tax functions remain scoped to US common equities.
This module is deliberately pure: it never sends orders or fetches credentials.
"""
import math

MARKETS = ("spot", "futures", "alpha", "us-stocks", "us-contracts", "saudi", "forex")
TIMEFRAMES = ("15m", "1h", "4h", "1d", "1w", "1M")

FRAME_RISK_LIMITS = {
    "15m": 3.5, "1h": 4.0, "4h": 5.0,
    "1d": 7.0, "1w": 12.0, "1M": 20.0,
}

UNIVERSAL_MODULES = (
    "risk", "budget", "alerts", "manual_ticket", "portfolio_rebalance",
)
US_EQUITY_MODULES = (
    "company_news_sec", "sec_xbrl_analyst", "financial_screener",
    "institutional_13f_copycat", "congress_ptr", "us_tax_lots_wash_sales",
)

def module_coverage(market):
    if market not in MARKETS:
        raise ValueError("unsupported market: " + str(market))
    coverage = {name: "adapted" for name in UNIVERSAL_MODULES}
    coverage["company_news_sec"] = "enabled" if market == "us-stocks" else "not_applicable"
    for name in US_EQUITY_MODULES[1:]:
        coverage[name] = "enabled" if market == "us-stocks" else "not_applicable"
    coverage["broker_execution"] = "disabled_manual_only"
    return coverage

def validate_signal(signal, timeframe):
    """Validate geometry and frame-aware structural risk without sizing an order."""
    if timeframe not in FRAME_RISK_LIMITS:
        return {"ok": False, "reasons": ["unsupported_timeframe"]}
    try:
        entry = float(signal["entry"])
        stop = float(signal["stop"])
        side = str(signal["side"]).upper()
        tp3 = float(signal["tp3"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return {"ok": False, "reasons": ["missing_or_invalid_levels"]}
    if not all(math.isfinite(x) and x > 0 for x in (entry, stop, tp3)):
        return {"ok": False, "reasons": ["non_positive_or_non_finite_levels"]}
    if side == "BUY":
        valid = stop < entry < tp3
        reward = tp3 - entry
        risk = entry - stop
    elif side == "SELL":
        valid = tp3 < entry < stop
        reward = entry - tp3
        risk = stop - entry
    else:
        return {"ok": False, "reasons": ["invalid_side"]}
    if not valid or risk <= 0:
        return {"ok": False, "reasons": ["invalid_stop_target_geometry"]}
    risk_pct = risk / entry * 100.0
    rr = reward / risk
    reasons = []
    if risk_pct > FRAME_RISK_LIMITS[timeframe]:
        reasons.append("frame_structural_risk_limit")
    if rr < 2.95:
        reasons.append("reward_risk_below_3R")
    return {
        "ok": not reasons,
        "reasons": reasons,
        "risk_pct": round(risk_pct, 4),
        "reward_risk": round(rr, 2),
        "max_risk_pct": FRAME_RISK_LIMITS[timeframe],
        "sizing": "not_calculated_account_equity_required",
    }

def alert_levels(signal, market, timeframe):
    """Return watch conditions; caller may persist/notify, no price polling here."""
    return {
        "market": market,
        "symbol": str(signal.get("symbol", "")).upper(),
        "timeframe": timeframe,
        "conditions": [
            {"type": "entry_touch", "price": signal.get("entry")},
            {"type": "stop", "price": signal.get("stop")},
            {"type": "target", "target": "TP1", "price": signal.get("tp1")},
            {"type": "target", "target": "TP2", "price": signal.get("tp2")},
            {"type": "target", "target": "TP3", "price": signal.get("tp3")},
        ],
    }

def apply_skill_stack(market, timeframe, signal):
    """Attach applicable skill coverage and deterministic checks to a signal."""
    if market not in MARKETS or timeframe not in TIMEFRAMES:
        return None
    risk = validate_signal(signal, timeframe)
    if not risk["ok"]:
        return None
    coverage = module_coverage(market)
    signal["skill_suite"] = {
        "version": "AS-TRADER-SKILL-ADAPTER-1",
        "market": market,
        "timeframe": timeframe,
        "coverage": coverage,
        "risk": risk,
        "budget": {
            "status": "ready_for_account_sized_calculation",
            "method": "risk_budget_divided_by_structural_stop_distance",
            "requires_account_equity": True,
        },
        "alerts": alert_levels(signal, market, timeframe),
        "broker": {"mode": "manual_paper_only", "execution_enabled": False},
        "portfolio": {"rebalance": "proposal_only", "auto_orders": False},
    }
    return signal

def status():
    return {
        "ok": True,
        "version": "AS-TRADER-SKILL-ADAPTER-1",
        "markets": {market: {"timeframes": list(TIMEFRAMES),
                             "modules": module_coverage(market)}
                    for market in MARKETS},
        "manual_only": True,
        "execution_enabled": False,
    }
